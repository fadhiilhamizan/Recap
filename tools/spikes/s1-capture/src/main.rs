//! Spike S1: capture mic + system audio di Windows, dua track WAV terpisah yang tahan crash.
//!
//! Desain mengikuti dokumen 03 (bagian 3.1) dan ADR-004/007/008:
//! - System audio: WASAPI process loopback mode EXCLUDE proses ini sendiri (fallback endpoint loopback).
//!   Process loopback tidak terikat device output, jadi tetap berjalan saat speaker/headset berganti.
//! - Mic: WASAPI shared mode pada device default; ikut berpindah saat device default berganti,
//!   dibuka ulang saat device dicabut, dan saat macet (tidak ada paket lebih dari 2 detik).
//! - Inti yang bisa diuji (supervisor + penulis) ada di `lib.rs`; uji otomatis di `tests/`.
//!
//! Subcommand:
//!   probe                       daftar perangkat + uji aktivasi process loopback
//!   record --out DIR --seconds N [--system process|endpoint|none] [--mic default|none]
//!   recover --dir DIR           perbaiki header WAV setelah proses dibunuh
//!   clicks --seconds N          putar klik tiap 10 detik (jalankan sebagai PROSES TERPISAH)
//!   watch-devices --seconds N   tampilkan notifikasi perubahan device (untuk uji manual)

use std::fs::{self, OpenOptions};
use std::io::{BufWriter, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

use anyhow::{bail, Context, Result};
use clap::{Parser, Subcommand, ValueEnum};
use crossbeam_channel::{bounded, RecvTimeoutError};
use s1_capture::{
    handle_event, supervise, Block, Channel, Clock, Event, Source, Stream, SupervisorConfig, TrackWriter, GAP_FILL_MIN_FRAMES, SR,
};
use wasapi::{
    initialize_mta, AudioCaptureClient, AudioClient, DeviceEnumerator, DeviceEventCallbacks, Direction, Handle, Role,
    SampleType, StreamMode, WaveFormat,
};

#[derive(Parser)]
#[command(about = "Spike S1 Recap: capture mic + system audio Windows")]
struct Cli {
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand)]
enum Cmd {
    Probe,
    Record {
        #[arg(long)]
        out: PathBuf,
        #[arg(long, default_value_t = 60)]
        seconds: u64,
        #[arg(long, value_enum, default_value_t = SystemMode::Process)]
        system: SystemMode,
        #[arg(long, value_enum, default_value_t = MicMode::Default)]
        mic: MicMode,
    },
    Recover {
        #[arg(long)]
        dir: PathBuf,
    },
    Clicks {
        #[arg(long, default_value_t = 60)]
        seconds: u64,
        #[arg(long, default_value_t = 10)]
        interval: u64,
    },
    WatchDevices {
        #[arg(long, default_value_t = 60)]
        seconds: u64,
    },
}

#[derive(Clone, Copy, ValueEnum, PartialEq, Debug)]
enum SystemMode {
    Process,
    Endpoint,
    None,
}

#[derive(Clone, Copy, ValueEnum, PartialEq, Debug)]
enum MicMode {
    Default,
    None,
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.cmd {
        Cmd::Probe => probe(),
        Cmd::Record { out, seconds, system, mic } => record(&out, seconds, system, mic),
        Cmd::Recover { dir } => recover(&dir),
        Cmd::Clicks { seconds, interval } => clicks(seconds, interval),
        Cmd::WatchDevices { seconds } => watch_devices(seconds),
    }
}

// ---------------------------------------------------------------- jam QPC

struct QpcClock;

impl Clock for QpcClock {
    fn now_100ns(&self) -> u64 {
        qpc_now_100ns()
    }
    fn sleep(&self, d: Duration) {
        thread::sleep(d)
    }
}

fn qpc_now_100ns() -> u64 {
    use windows_sys::Win32::System::Performance::{QueryPerformanceCounter, QueryPerformanceFrequency};
    let (mut c, mut f) = (0i64, 0i64);
    unsafe {
        QueryPerformanceCounter(&mut c);
        QueryPerformanceFrequency(&mut f);
    }
    ((c as i128 * 10_000_000) / f as i128) as u64
}

fn format48k_mono() -> WaveFormat {
    WaveFormat::new(32, 32, &SampleType::Float, SR as usize, 1, None)
}

fn shared_mode() -> StreamMode {
    StreamMode::EventsShared { autoconvert: true, buffer_duration_hns: 200_000 }
}

// ---------------------------------------------------------------- sumber WASAPI

struct WasapiSource {
    ch: Channel,
    system: SystemMode,
    com_ready: bool,
}

struct WasapiStream {
    ch: Channel,
    client: AudioClient,
    capture: AudioCaptureClient,
    event: Handle,
    buf: Vec<u8>,
}

impl Drop for WasapiStream {
    fn drop(&mut self) {
        let _ = self.client.stop_stream();
    }
}

impl Source for WasapiSource {
    fn channel(&self) -> Channel {
        self.ch
    }

    fn may_be_quiet(&self) -> bool {
        // Loopback tidak mengirim paket saat tidak ada audio diputar; mic selalu mengirim paket.
        self.ch == Channel::System
    }

    fn open(&mut self) -> Result<(Box<dyn Stream>, String)> {
        if !self.com_ready {
            initialize_mta().ok().context("COM MTA")?;
            self.com_ready = true;
        }
        let (mut client, device) = match (self.ch, self.system) {
            (Channel::System, SystemMode::Process) => (
                AudioClient::new_application_loopback_client(std::process::id(), false).context("aktivasi process loopback")?,
                "process-loopback(exclude-self)".to_string(),
            ),
            (Channel::System, _) => {
                let dev = DeviceEnumerator::new()?.get_default_device(&Direction::Render)?;
                let name = format!("endpoint-loopback:{}", dev.get_friendlyname().unwrap_or_default());
                (dev.get_iaudioclient()?, name)
            }
            (Channel::Mic, _) => {
                let dev = DeviceEnumerator::new()?.get_default_device(&Direction::Capture)?;
                let name = dev.get_friendlyname().unwrap_or_default();
                (dev.get_iaudioclient()?, name)
            }
        };
        client.initialize_client(&format48k_mono(), &Direction::Capture, &shared_mode())?;
        let event = client.set_get_eventhandle()?;
        let capture = client.get_audiocaptureclient()?;
        client.start_stream()?;
        let stream = WasapiStream { ch: self.ch, client, capture, event, buf: vec![0u8; SR as usize * 4] };
        Ok((Box::new(stream), device))
    }
}

impl Stream for WasapiStream {
    fn read(&mut self, timeout: Duration) -> Result<Vec<Block>> {
        // Timeout dianggap wajar (loopback tanpa audio); error lain (device hilang) muncul dari pembacaan.
        let _ = self.event.wait_for_event(timeout.as_millis() as u32);
        let mut out = Vec::new();
        loop {
            let pending = self.capture.get_next_packet_size()?.unwrap_or(0);
            if pending == 0 {
                break;
            }
            let (frames, info) = self.capture.read_from_device(&mut self.buf)?;
            if frames == 0 {
                break;
            }
            let mut samples: Vec<f32> = self.buf[..frames as usize * 4]
                .chunks_exact(4)
                .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
                .collect();
            if info.flags.silent {
                samples.iter_mut().for_each(|s| *s = 0.0);
            }
            out.push(Block { ch: self.ch, qpc_100ns: info.timestamp, samples, silent: info.flags.silent, discontinuity: info.flags.data_discontinuity });
        }
        Ok(out)
    }
}

// ---------------------------------------------------------------- probe

fn probe() -> Result<()> {
    initialize_mta().ok().context("COM MTA")?;
    let en = DeviceEnumerator::new()?;
    for dir in [Direction::Capture, Direction::Render] {
        let def = en.get_default_device(&dir)?;
        println!("default {:?}: {}", dir, def.get_friendlyname()?);
        for dev in &en.get_device_collection(&dir)? {
            println!("  - {}", dev?.get_friendlyname()?);
        }
    }
    match AudioClient::new_application_loopback_client(std::process::id(), false)
        .and_then(|mut c| c.initialize_client(&format48k_mono(), &Direction::Capture, &shared_mode()).map(|_| c))
    {
        Ok(_) => println!("process loopback (exclude self): TERSEDIA"),
        Err(e) => println!("process loopback (exclude self): TIDAK tersedia ({e})"),
    }
    Ok(())
}

// ---------------------------------------------------------------- record

fn record(out: &Path, seconds: u64, system: SystemMode, mic: MicMode) -> Result<()> {
    fs::create_dir_all(out)?;
    initialize_mta().ok().context("COM MTA")?;
    let stop = Arc::new(AtomicBool::new(false));
    {
        let stop = stop.clone();
        ctrlc::set_handler(move || stop.store(true, Ordering::Relaxed))?;
    }
    let mut channels = vec![];
    if mic == MicMode::Default {
        channels.push(Channel::Mic);
    }
    if system != SystemMode::None {
        channels.push(Channel::System);
    }
    if channels.is_empty() {
        bail!("tidak ada sumber yang dipilih");
    }

    // Permintaan buka ulang dari notifikasi device default (mic; dan system bila endpoint loopback).
    let reopen_mic = Arc::new(AtomicBool::new(false));
    let reopen_sys = Arc::new(AtomicBool::new(false));
    let mut callbacks = DeviceEventCallbacks::new();
    {
        let (rm, rs) = (reopen_mic.clone(), reopen_sys.clone());
        let follow_render = system == SystemMode::Endpoint;
        callbacks.set_default_device_callback(move |dir, role, _id| {
            if !matches!(role, Role::Console) {
                return; // satu notifikasi per perubahan cukup
            }
            match dir {
                Direction::Capture => rm.store(true, Ordering::Relaxed),
                Direction::Render if follow_render => rs.store(true, Ordering::Relaxed),
                _ => {}
            }
        });
    }
    let _registration = DeviceEnumerator::new()?.register_notification_callback(callbacks)?;

    let clock: Arc<dyn Clock> = Arc::new(QpcClock);
    let (tx, rx) = bounded::<Event>(8192);
    let t0 = qpc_now_100ns(); // jam bersama untuk kedua kanal
    let mut handles = vec![];
    for ch in channels.clone() {
        let (tx, stop, clock) = (tx.clone(), stop.clone(), clock.clone());
        let reopen = if ch == Channel::Mic { reopen_mic.clone() } else { reopen_sys.clone() };
        let source = Box::new(WasapiSource { ch, system, com_ready: false });
        handles.push(thread::Builder::new().name(format!("cap-{}", ch.name())).spawn(move || {
            supervise(source, clock, SupervisorConfig::default(), reopen, stop, |ev| tx.send(ev).is_ok());
        })?);
    }
    drop(tx);

    let mut writers: Vec<TrackWriter> = channels.iter().map(|&c| TrackWriter::new(out, c)).collect::<Result<_>>()?;
    let mut timeline = BufWriter::new(OpenOptions::new().create(true).append(true).open(out.join("timeline.jsonl"))?);
    writeln!(timeline, "{}", serde_json::json!({"event": "start", "t0_qpc": t0, "sr": SR, "system_mode": format!("{system:?}")}))?;

    let started = Instant::now();
    let mut last_report = Instant::now();
    while started.elapsed() < Duration::from_secs(seconds) && !stop.load(Ordering::Relaxed) {
        match rx.recv_timeout(Duration::from_millis(200)) {
            Ok(ev) => handle_event(ev, &mut writers, t0, &mut timeline)?,
            Err(RecvTimeoutError::Timeout) => {}
            Err(RecvTimeoutError::Disconnected) => break,
        }
        // Kanal yang wajar diam (loopback tanpa audio): majukan timeline dengan nol sampai "sekarang - 200 ms".
        let now_pos = ((qpc_now_100ns() - t0) as i128 * SR as i128 / 10_000_000) as i64 - (SR as i64 / 5);
        for w in writers.iter_mut().filter(|w| w.ch == Channel::System) {
            if now_pos - w.pos > GAP_FILL_MIN_FRAMES * 10 {
                w.advance_to(now_pos, &mut timeline)?;
            }
        }
        if last_report.elapsed() >= Duration::from_secs(10) {
            report(&writers, t0, started);
            timeline.flush()?;
            last_report = Instant::now();
        }
    }
    stop.store(true, Ordering::Relaxed);
    while let Ok(ev) = rx.recv_timeout(Duration::from_millis(300)) {
        handle_event(ev, &mut writers, t0, &mut timeline)?;
    }
    for h in handles {
        let _ = h.join();
    }
    for w in writers.iter_mut() {
        w.finish()?;
    }
    report(&writers, t0, started);
    writeln!(timeline, "{}", serde_json::json!({"event": "stop", "qpc": qpc_now_100ns()}))?;
    timeline.flush()?;
    Ok(())
}

fn report(writers: &[TrackWriter], t0: u64, started: Instant) {
    let wall = (qpc_now_100ns() - t0) as f64 / 1e7;
    let mut obj = serde_json::json!({"event": "health", "elapsed_s": (started.elapsed().as_secs_f64() * 10.0).round() / 10.0});
    for w in writers {
        obj[w.ch.name()] = serde_json::json!({
            "timeline_s": w.pos as f64 / SR as f64,
            "written_s": w.frames_written as f64 / SR as f64,
            "lag_vs_clock_ms": ((wall - w.pos as f64 / SR as f64) * 1000.0).round(),
            "gaps_filled": w.gaps_filled, "gap_s": w.gap_frames as f64 / SR as f64,
            "long_gaps": w.long_gaps, "long_gap_s": w.long_gap_frames as f64 / SR as f64,
            "reopens": w.reopens, "discontinuities": w.discontinuities, "files": w.seq,
        });
    }
    println!("{obj}");
}

// ---------------------------------------------------------------- recover

/// Perbaiki header WAV yang tidak final (proses dibunuh): ukuran data dihitung dari ukuran file.
fn recover(dir: &Path) -> Result<()> {
    for ch in ["mic", "system"] {
        let d = dir.join("audio").join(ch);
        if !d.exists() {
            continue;
        }
        let mut files: Vec<_> = fs::read_dir(&d)?.filter_map(|e| e.ok()).map(|e| e.path())
            .filter(|p| p.extension().is_some_and(|x| x == "wav")).collect();
        files.sort();
        for p in files {
            let len = fs::metadata(&p)?.len();
            if len < 44 {
                continue;
            }
            let data_len = ((len - 44) / 2 * 2) as u32;
            let mut f = OpenOptions::new().read(true).write(true).open(&p)?;
            f.seek(SeekFrom::Start(4))?;
            f.write_all(&(36 + data_len).to_le_bytes())?;
            f.seek(SeekFrom::Start(40))?;
            f.write_all(&data_len.to_le_bytes())?;
            println!("{}: {:.1} s dipulihkan", p.display(), data_len as f64 / 2.0 / SR as f64);
        }
    }
    Ok(())
}

// ---------------------------------------------------------------- clicks dan watch-devices

fn clicks(seconds: u64, interval: u64) -> Result<()> {
    initialize_mta().ok().context("COM MTA")?;
    let dev = DeviceEnumerator::new()?.get_default_device(&Direction::Render)?;
    let mut client = dev.get_iaudioclient()?;
    client.initialize_client(&format48k_mono(), &Direction::Render, &shared_mode())?;
    let event = client.set_get_eventhandle()?;
    let render = client.get_audiorenderclient()?;
    client.start_stream()?;
    let (total, period) = (seconds * SR as u64, interval * SR as u64);
    let mut pos: u64 = 0;
    while pos < total {
        let frames = client.get_available_space_in_frames()? as u64;
        let mut data = Vec::with_capacity(frames as usize * 4);
        for i in 0..frames {
            let t = (pos + i) % period;
            let s: f32 = if t < SR as u64 / 200 { 0.8 * (2.0 * std::f32::consts::PI * 1000.0 * t as f32 / SR as f32).sin() } else { 0.0 };
            data.extend_from_slice(&s.to_le_bytes());
        }
        render.write_to_device(frames as usize, &data, None)?;
        pos += frames;
        event.wait_for_event(1000)?;
    }
    client.stop_stream()?;
    Ok(())
}

fn watch_devices(seconds: u64) -> Result<()> {
    initialize_mta().ok().context("COM MTA")?;
    let mut cb = DeviceEventCallbacks::new();
    cb.set_default_device_callback(|dir, role, id| println!("default {dir} {role}: {id:?}"));
    cb.set_device_state_callback(|id, state| println!("state {id}: {state}"));
    cb.set_device_added_callback(|id| println!("added {id}"));
    cb.set_device_removed_callback(|id| println!("removed {id}"));
    let _reg = DeviceEnumerator::new()?.register_notification_callback(cb)?;
    thread::sleep(Duration::from_secs(seconds));
    Ok(())
}
