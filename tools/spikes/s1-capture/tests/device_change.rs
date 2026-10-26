//! Uji ketahanan capture terhadap perubahan device tanpa hardware: sumber palsu + jam virtual.
//!
//! Skenario mencerminkan tes manual yang tertunda (colok/lepas headset, ganti device default,
//! Bluetooth berganti mode, sleep/resume): stream error lalu dibuka ulang, mungkin ke device lain.

use std::collections::VecDeque;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use anyhow::{anyhow, Result};
use s1_capture::*;

const BLOCK: usize = 480; // 10 ms pada 48 kHz, sama dengan paket WASAPI

/// Jam virtual: waktu hanya maju lewat `sleep`. Saat melewati batas waktu uji, `stop` dinyalakan,
/// sehingga supervisor berhenti walau tidak ada event (misalnya loopback hening).
struct FakeClock {
    now: AtomicU64,
    deadline_100ns: u64,
    stop: Arc<AtomicBool>,
}

impl Clock for FakeClock {
    fn now_100ns(&self) -> u64 {
        self.now.load(Ordering::SeqCst)
    }
    fn sleep(&self, d: Duration) {
        let t = self.now.fetch_add(d.as_nanos() as u64 / 100, Ordering::SeqCst) + d.as_nanos() as u64 / 100;
        if t >= self.deadline_100ns {
            self.stop.store(true, Ordering::SeqCst);
        }
    }
}

/// Rencana untuk satu panggilan `open()`.
#[derive(Clone)]
enum Plan {
    Fail,
    Ok { device: &'static str, value: f32, blocks_then_error: Option<usize>, jump_before_error_s: u64, mute_after: Option<usize> },
}

struct FakeSource {
    ch: Channel,
    quiet: bool,
    clock: Arc<FakeClock>,
    plans: Arc<Mutex<VecDeque<Plan>>>,
    opens: Arc<AtomicU64>,
}

struct FakeStream {
    ch: Channel,
    clock: Arc<FakeClock>,
    value: f32,
    left: Option<usize>,
    jump_s: u64,
    mute_after: Option<usize>,
    produced: usize,
}

impl Source for FakeSource {
    fn channel(&self) -> Channel {
        self.ch
    }
    fn may_be_quiet(&self) -> bool {
        self.quiet
    }
    fn open(&mut self) -> Result<(Box<dyn Stream>, String)> {
        self.opens.fetch_add(1, Ordering::SeqCst);
        // Rencana terakhir dipakai terus bila daftar habis.
        let plan = {
            let mut p = self.plans.lock().unwrap();
            if p.len() > 1 { p.pop_front().unwrap() } else { p.front().cloned().unwrap() }
        };
        match plan {
            Plan::Fail => Err(anyhow!("AUDCLNT_E_DEVICE_INVALIDATED (simulasi)")),
            Plan::Ok { device, value, blocks_then_error, jump_before_error_s, mute_after } => Ok((
                Box::new(FakeStream { ch: self.ch, clock: self.clock.clone(), value, left: blocks_then_error,
                                      jump_s: jump_before_error_s, mute_after, produced: 0 }),
                device.to_string(),
            )),
        }
    }
}

impl Stream for FakeStream {
    fn read(&mut self, timeout: Duration) -> Result<Vec<Block>> {
        if let Some(0) = self.left {
            self.clock.sleep(Duration::from_secs(self.jump_s)); // misalnya laptop tidur
            return Err(anyhow!("AUDCLNT_E_DEVICE_INVALIDATED (simulasi)"));
        }
        if self.mute_after.is_some_and(|m| self.produced >= m) {
            self.clock.sleep(timeout); // stream hidup tapi tidak mengirim paket (macet / loopback hening)
            return Ok(vec![]);
        }
        let ts = self.clock.now_100ns();
        self.clock.sleep(Duration::from_millis(10));
        self.left = self.left.map(|n| n - 1);
        self.produced += 1;
        Ok(vec![Block { ch: self.ch, qpc_100ns: ts, samples: vec![self.value; BLOCK], silent: false, discontinuity: false }])
    }
}

struct Run {
    events: Vec<Event>,
    opens: u64,
    clock: Arc<FakeClock>,
}

/// Jalankan supervisor sampai jam virtual mencapai `seconds`; `reopen_at_s` mensimulasikan
/// notifikasi "device default berganti".
fn run(ch: Channel, quiet: bool, plans: Vec<Plan>, seconds: f64, reopen_at_s: Option<f64>) -> Run {
    let stop = Arc::new(AtomicBool::new(false));
    let clock = Arc::new(FakeClock { now: AtomicU64::new(0), deadline_100ns: (seconds * 1e7) as u64, stop: stop.clone() });
    let opens = Arc::new(AtomicU64::new(0));
    let src = FakeSource { ch, quiet, clock: clock.clone(), plans: Arc::new(Mutex::new(plans.into())), opens: opens.clone() };
    let reopen = Arc::new(AtomicBool::new(false));
    let mut events = vec![];
    let (c2, r2) = (clock.clone(), reopen.clone());
    let mut reopen_sent = false;
    supervise(Box::new(src), clock.clone(), SupervisorConfig::default(), reopen.clone(), stop, |ev| {
        events.push(ev);
        let t = c2.now_100ns() as f64 / 1e7;
        if let Some(at) = reopen_at_s {
            if !reopen_sent && t >= at {
                r2.store(true, Ordering::SeqCst);
                reopen_sent = true;
            }
        }
        true
    });
    Run { events, opens: opens.load(Ordering::SeqCst), clock }
}

fn tmpdir(name: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("s1-test-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn write_all(dir: &PathBuf, events: Vec<Event>, channels: &[Channel]) -> (Vec<TrackWriter>, String) {
    let mut writers: Vec<TrackWriter> = channels.iter().map(|&c| TrackWriter::new(dir, c).unwrap()).collect();
    let mut tl: Vec<u8> = vec![];
    for ev in events {
        handle_event(ev, &mut writers, 0, &mut tl).unwrap();
    }
    for w in writers.iter_mut() {
        w.finish().unwrap();
    }
    (writers, String::from_utf8(tl).unwrap())
}

fn read_track(dir: &PathBuf, ch: Channel) -> Vec<i16> {
    let mut files: Vec<_> = std::fs::read_dir(dir.join("audio").join(ch.name())).unwrap().map(|e| e.unwrap().path()).collect();
    files.sort();
    files.iter().flat_map(|f| hound::WavReader::open(f).unwrap().into_samples::<i16>().map(|s| s.unwrap()).collect::<Vec<_>>()).collect()
}

fn ok(device: &'static str, value: f32, blocks_then_error: Option<usize>) -> Plan {
    Plan::Ok { device, value, blocks_then_error, jump_before_error_s: 0, mute_after: None }
}

#[test]
fn headset_dicabut_lalu_pindah_ke_mic_internal() {
    // 3 detik di headset, device hilang, 3 kali gagal dibuka, lalu berhasil di mic internal.
    let r = run(Channel::Mic, false, vec![ok("Headset USB", 0.5, Some(300)), Plan::Fail, Plan::Fail, Plan::Fail, ok("Mic internal", 0.25, None)], 10.0, None);
    assert_eq!(r.opens, 5, "harus mencoba lagi sampai berhasil");
    let dir = tmpdir("dicabut");
    let (w, tl) = write_all(&dir, r.events, &[Channel::Mic]);
    let w = &w[0];
    // Timeline tetap sejajar jam: total posisi sekitar 10 detik.
    let total_s = w.pos as f64 / SR as f64;
    assert!((total_s - 10.0).abs() < 0.05, "timeline {total_s} s, seharusnya sekitar 10 s");
    // Waktu tanpa device (backoff 100+200+500 ms) diisi nol sebagai satu celah.
    assert_eq!(w.gaps_filled, 1);
    let gap_s = w.gap_frames as f64 / SR as f64;
    assert!((0.7..1.0).contains(&gap_s), "celah {gap_s} s");
    assert_eq!(w.reopens, 1);
    assert!(tl.contains("\"event\":\"lost\"") && tl.contains("Mic internal"));
    // Isi audio: bagian headset, nol, lalu bagian mic internal; tidak ada data yang tertukar/hilang.
    let s = read_track(&dir, Channel::Mic);
    let headset = (0.5 * i16::MAX as f32) as i16;
    let internal = (0.25 * i16::MAX as f32) as i16;
    assert!(s[..SR as usize * 3 - 10].iter().all(|&v| v == headset));
    assert!(s[SR as usize * 4..].iter().all(|&v| v == internal));
    assert_eq!(s.iter().filter(|&&v| v == headset).count(), 300 * BLOCK, "3 detik headset utuh");
}

#[test]
fn device_default_berganti_dibuka_ulang_sekali() {
    let r = run(Channel::Mic, false, vec![ok("Mic internal", 0.25, None), ok("Headset Bluetooth (Hands-Free)", 0.5, None)], 8.0, Some(3.0));
    assert_eq!(r.opens, 2, "satu buka ulang karena notifikasi default berganti");
    let dir = tmpdir("default");
    let (w, tl) = write_all(&dir, r.events, &[Channel::Mic]);
    assert!(tl.contains("device default berganti"));
    assert!((w[0].pos as f64 / SR as f64 - 8.0).abs() < 0.05);
    // Celah hanya selama debounce (300 ms), diisi nol.
    let gap_s = w[0].gap_frames as f64 / SR as f64;
    assert!((0.25..0.4).contains(&gap_s), "celah {gap_s} s");
}

#[test]
fn mic_macet_dibuka_ulang_oleh_watchdog() {
    // Stream hidup tapi berhenti mengirim paket setelah 1 detik (driver macet).
    let stuck = Plan::Ok { device: "Mic internal", value: 0.25, blocks_then_error: None, jump_before_error_s: 0, mute_after: Some(100) };
    let r = run(Channel::Mic, false, vec![stuck, ok("Mic internal", 0.25, None)], 6.0, None);
    assert_eq!(r.opens, 2);
    let dir = tmpdir("macet");
    let (w, tl) = write_all(&dir, r.events, &[Channel::Mic]);
    assert!(tl.contains("tidak ada paket"));
    assert!((w[0].pos as f64 / SR as f64 - 6.0).abs() < 0.05);
}

#[test]
fn loopback_hening_tidak_dibuka_ulang() {
    // Process loopback tanpa audio diputar: tidak ada paket, dan itu wajar.
    let quiet = Plan::Ok { device: "process-loopback", value: 0.1, blocks_then_error: None, jump_before_error_s: 0, mute_after: Some(50) };
    let r = run(Channel::System, true, vec![quiet], 20.0, None);
    assert_eq!(r.opens, 1, "tidak boleh dibuka ulang hanya karena hening");
    assert!(r.clock.now_100ns() as f64 / 1e7 >= 20.0);
}

#[test]
fn sleep_satu_jam_tidak_menulis_satu_jam_nol() {
    // 2 detik rekam, laptop tidur 1 jam (device invalid saat bangun), lalu lanjut 2 detik.
    let sleepy = Plan::Ok { device: "Mic internal", value: 0.25, blocks_then_error: Some(200), jump_before_error_s: 3600, mute_after: None };
    let r = run(Channel::Mic, false, vec![sleepy, ok("Mic internal", 0.25, None)], 3604.0, None);
    let dir = tmpdir("sleep");
    let (w, tl) = write_all(&dir, r.events, &[Channel::Mic]);
    let w = &w[0];
    assert_eq!(w.long_gaps, 1);
    assert!(tl.contains("\"event\":\"long_gap\""));
    let written_s = w.frames_written as f64 / SR as f64;
    assert!(written_s < 10.0, "hanya audio nyata yang ditulis ({written_s} s), bukan 1 jam nol");
    assert!(w.seq >= 2, "file baru setelah celah panjang");
    assert!((w.pos as f64 / SR as f64 - 3604.0).abs() < 0.1, "posisi timeline tetap mengikuti jam");
}

#[test]
fn dua_kanal_tetap_sejajar_setelah_gangguan_mic() {
    // System mengalir terus 10 detik; mic putus 1 detik di tengah. Di akhir posisi keduanya sama.
    let r = run(Channel::Mic, false, vec![ok("Headset USB", 0.5, Some(400)), Plan::Fail, Plan::Fail, Plan::Fail, Plan::Fail, ok("Mic internal", 0.25, None)], 10.0, None);
    let mut events = r.events;
    for i in 0..1000u64 {
        events.push(Event::Audio(Block { ch: Channel::System, qpc_100ns: i * 100_000, samples: vec![0.1; BLOCK], silent: false, discontinuity: false }));
    }
    let dir = tmpdir("sejajar");
    let (w, _) = write_all(&dir, events, &[Channel::Mic, Channel::System]);
    let (mic, sys) = (w[0].pos, w[1].pos);
    let diff_ms = (mic - sys).abs() as f64 / SR as f64 * 1000.0;
    assert!(diff_ms <= 20.0, "selisih posisi mic vs system {diff_ms} ms");
}
