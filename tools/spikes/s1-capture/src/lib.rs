//! Inti capture S1 yang bisa diuji tanpa hardware: supervisor sumber audio (buka ulang saat
//! device hilang/berganti), dan penulis track WAV crash-safe dengan timeline berbasis jam QPC.
//!
//! Sumber nyata (WASAPI) ada di `main.rs`; uji otomatis memakai sumber palsu (`tests/`).

use std::fs;
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;

pub const SR: u32 = 48_000;
pub const CHUNK_SECONDS: u64 = 300;
/// Celah di atas 20 ms diisi nol agar dua kanal tetap sejajar.
pub const GAP_FILL_MIN_FRAMES: i64 = (SR / 50) as i64;
/// Celah di atas 30 detik (sleep/resume, device hilang lama) tidak diisi nol: dicatat sebagai
/// penanda di timeline dan file baru dimulai, agar tidak menulis berjam-jam keheningan.
pub const GAP_FILL_MAX_FRAMES: i64 = (SR as i64) * 30;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Channel {
    Mic,
    System,
}

impl Channel {
    pub fn name(self) -> &'static str {
        match self {
            Channel::Mic => "mic",
            Channel::System => "system",
        }
    }
}

/// Satu blok audio mono 48 kHz dari sumber.
#[derive(Clone, Debug)]
pub struct Block {
    pub ch: Channel,
    /// Timestamp sampel pertama, satuan 100 ns pada jam QPC.
    pub qpc_100ns: u64,
    pub samples: Vec<f32>,
    pub silent: bool,
    pub discontinuity: bool,
}

/// Peristiwa yang dikirim ke thread penulis: blok audio atau perubahan status sumber.
#[derive(Debug)]
pub enum Event {
    Audio(Block),
    Opened { ch: Channel, device: String, attempt: u32, qpc_100ns: u64 },
    Lost { ch: Channel, reason: String, qpc_100ns: u64 },
}

/// Stream yang sedang terbuka. `read` menunggu sebentar lalu mengembalikan blok yang tersedia.
pub trait Stream {
    fn read(&mut self, timeout: Duration) -> Result<Vec<Block>>;
}

/// Pembuka stream untuk satu kanal (WASAPI nyata atau palsu untuk uji).
pub trait Source: Send {
    fn channel(&self) -> Channel;
    fn open(&mut self) -> Result<(Box<dyn Stream>, String)>;
    /// Sumber yang wajar diam tanpa paket (process loopback saat tidak ada audio diputar).
    fn may_be_quiet(&self) -> bool;
}

pub trait Clock: Send + Sync {
    fn now_100ns(&self) -> u64;
    fn sleep(&self, d: Duration);
}

/// Kebijakan supervisor.
#[derive(Clone, Debug)]
pub struct SupervisorConfig {
    /// Bila sumber yang seharusnya selalu mengirim paket (mic) diam selama ini, buka ulang.
    pub stall_timeout: Duration,
    pub backoff: Vec<Duration>,
    /// Setelah permintaan buka ulang (misalnya device default berganti), tunggu tenang selama ini.
    pub reopen_debounce: Duration,
}

impl Default for SupervisorConfig {
    fn default() -> Self {
        Self {
            stall_timeout: Duration::from_secs(2),
            backoff: [100, 200, 500, 1000, 2000].into_iter().map(Duration::from_millis).collect(),
            reopen_debounce: Duration::from_millis(300),
        }
    }
}

/// Jalankan satu kanal sampai `stop`: buka, baca, dan buka ulang bila gagal, macet, atau diminta.
/// Tidak pernah berhenti karena error device; hanya `stop` yang mengakhiri.
pub fn supervise(
    mut source: Box<dyn Source>,
    clock: Arc<dyn Clock>,
    cfg: SupervisorConfig,
    reopen: Arc<AtomicBool>,
    stop: Arc<AtomicBool>,
    mut emit: impl FnMut(Event) -> bool,
) {
    let ch = source.channel();
    let mut attempt: u32 = 0;
    while !stop.load(Ordering::Relaxed) {
        let (mut stream, device) = match source.open() {
            Ok(s) => s,
            Err(e) => {
                let wait = cfg.backoff[(attempt as usize).min(cfg.backoff.len() - 1)];
                attempt += 1;
                if !emit(Event::Lost { ch, reason: format!("buka gagal: {e}"), qpc_100ns: clock.now_100ns() }) {
                    return;
                }
                clock.sleep(wait);
                continue;
            }
        };
        if !emit(Event::Opened { ch, device, attempt, qpc_100ns: clock.now_100ns() }) {
            return;
        }
        attempt = 0;
        reopen.store(false, Ordering::Relaxed);
        let mut last_packet = clock.now_100ns();
        let reason = loop {
            if stop.load(Ordering::Relaxed) {
                return;
            }
            if reopen.swap(false, Ordering::Relaxed) {
                // Debounce: Windows mengirim beberapa notifikasi default-device berturut-turut.
                clock.sleep(cfg.reopen_debounce);
                reopen.store(false, Ordering::Relaxed);
                break "device default berganti".to_string();
            }
            match stream.read(Duration::from_millis(100)) {
                Ok(blocks) => {
                    if !blocks.is_empty() {
                        last_packet = clock.now_100ns();
                    }
                    for b in blocks {
                        if !emit(Event::Audio(b)) {
                            return;
                        }
                    }
                    let idle = Duration::from_nanos((clock.now_100ns() - last_packet) * 100);
                    if !source.may_be_quiet() && idle >= cfg.stall_timeout {
                        break format!("tidak ada paket selama {:.1} s", idle.as_secs_f64());
                    }
                }
                Err(e) => break format!("stream error: {e}"),
            }
        };
        drop(stream);
        if !emit(Event::Lost { ch, reason, qpc_100ns: clock.now_100ns() }) {
            return;
        }
    }
}

/// Penulis satu kanal: WAV 16-bit per 5 menit, flush tiap detik, celah diisi sesuai jam QPC.
pub struct TrackWriter {
    pub dir: PathBuf,
    pub ch: Channel,
    pub seq: u32,
    wav: Option<hound::WavWriter<BufWriter<fs::File>>>,
    frames_in_chunk: u64,
    /// Posisi timeline (frame sejak t0), termasuk isian nol dan celah panjang yang dilompati.
    pub pos: i64,
    pub frames_written: i64,
    pub gaps_filled: u64,
    pub gap_frames: i64,
    pub long_gaps: u64,
    pub long_gap_frames: i64,
    pub discontinuities: u64,
    pub reopens: u64,
    unflushed: u64,
}

impl TrackWriter {
    pub fn new(root: &Path, ch: Channel) -> Result<Self> {
        let dir = root.join("audio").join(ch.name());
        fs::create_dir_all(&dir)?;
        Ok(Self {
            dir, ch, seq: 0, wav: None, frames_in_chunk: 0, pos: 0, frames_written: 0, gaps_filled: 0,
            gap_frames: 0, long_gaps: 0, long_gap_frames: 0, discontinuities: 0, reopens: 0, unflushed: 0,
        })
    }

    fn rotate(&mut self) -> Result<()> {
        if let Some(w) = self.wav.take() {
            w.finalize()?;
        }
        self.seq += 1;
        let spec = hound::WavSpec { channels: 1, sample_rate: SR, bits_per_sample: 16, sample_format: hound::SampleFormat::Int };
        self.wav = Some(hound::WavWriter::create(self.dir.join(format!("{:06}.wav", self.seq)), spec)?);
        self.frames_in_chunk = 0;
        Ok(())
    }

    fn write_samples(&mut self, samples: impl Iterator<Item = f32>) -> Result<()> {
        for s in samples {
            if self.wav.is_none() || self.frames_in_chunk >= CHUNK_SECONDS * SR as u64 {
                self.rotate()?;
            }
            self.wav.as_mut().unwrap().write_sample((s.clamp(-1.0, 1.0) * i16::MAX as f32) as i16)?;
            self.frames_in_chunk += 1;
            self.frames_written += 1;
            self.pos += 1;
            self.unflushed += 1;
        }
        if self.unflushed >= SR as u64 {
            if let Some(w) = self.wav.as_mut() {
                w.flush()?; // hound memperbarui header saat flush: file selalu bisa dibuka
            }
            self.unflushed = 0;
        }
        Ok(())
    }

    /// Majukan timeline ke `target` (frame sejak t0): isi nol bila celah wajar, lompati bila panjang.
    /// Mengembalikan (celah, dilompati?).
    pub fn advance_to(&mut self, target: i64, timeline: &mut impl Write) -> Result<(i64, bool)> {
        let gap = target - self.pos;
        if gap <= GAP_FILL_MIN_FRAMES {
            return Ok((gap.max(0), false));
        }
        if gap > GAP_FILL_MAX_FRAMES {
            self.long_gaps += 1;
            self.long_gap_frames += gap;
            writeln!(timeline, "{}", serde_json::json!({"event": "long_gap", "ch": self.ch.name(), "from_pos": self.pos,
                "to_pos": target, "gap_s": gap as f64 / SR as f64, "next_file": self.seq + 1}))?;
            self.pos = target;
            self.rotate()?; // file baru; posisi awalnya tercatat di timeline
            return Ok((gap, true));
        }
        self.gaps_filled += 1;
        self.gap_frames += gap;
        self.write_samples(std::iter::repeat(0.0).take(gap as usize))?;
        Ok((gap, false))
    }

    pub fn push(&mut self, b: &Block, t0: u64, timeline: &mut impl Write) -> Result<()> {
        let expected = ((b.qpc_100ns.saturating_sub(t0)) as i128 * SR as i128 / 10_000_000) as i64;
        let (gap, skipped) = self.advance_to(expected, timeline)?;
        if b.discontinuity {
            self.discontinuities += 1;
        }
        let before = self.pos;
        self.write_samples(b.samples.iter().copied())?;
        writeln!(timeline, "{}", serde_json::json!({"ch": self.ch.name(), "qpc": b.qpc_100ns, "frames": b.samples.len(),
            "pos": before, "gap": gap, "skipped": skipped, "silent": b.silent, "disc": b.discontinuity}))?;
        Ok(())
    }

    pub fn finish(&mut self) -> Result<()> {
        if let Some(w) = self.wav.take() {
            w.finalize()?;
        }
        Ok(())
    }
}

/// Hubungkan peristiwa ke penulis: blok ditulis, status sumber dicatat ke timeline.
pub fn handle_event(ev: Event, writers: &mut [TrackWriter], t0: u64, timeline: &mut impl Write) -> Result<()> {
    match ev {
        Event::Audio(b) => {
            let w = writers.iter_mut().find(|w| w.ch == b.ch).expect("writer untuk kanal");
            w.push(&b, t0, timeline)?;
        }
        Event::Opened { ch, device, attempt, qpc_100ns } => {
            if let Some(w) = writers.iter_mut().find(|w| w.ch == ch) {
                if w.frames_written > 0 {
                    w.reopens += 1;
                }
            }
            writeln!(timeline, "{}", serde_json::json!({"event": "opened", "ch": ch.name(), "device": device, "attempt": attempt, "qpc": qpc_100ns}))?;
        }
        Event::Lost { ch, reason, qpc_100ns } => {
            writeln!(timeline, "{}", serde_json::json!({"event": "lost", "ch": ch.name(), "reason": reason, "qpc": qpc_100ns}))?;
        }
    }
    Ok(())
}
