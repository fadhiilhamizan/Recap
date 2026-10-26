//! Sidecar tiruan (spike S8). Berbicara protokol `recap-sidecar` lewat stdin/stdout:
//! kirim `hello`, jawab `ping`, kirim `health` tiap detik dan frame audio palsu tiap 100 ms
//! (16 kHz mono f32, kanal "system"). Perintah `crash` = abort, `stall` = berhenti menjawab.
//! Keluar dengan rapi saat stdin ditutup (proses induk mati) atau menerima `shutdown`.

use std::io::{self, Write};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc};
use std::thread;
use std::time::{Duration, Instant};

use recap_sidecar::{read_frame, write_frame, AudioHeader, Control, Frame, PROTOCOL_VERSION};

fn main() {
    let started = Instant::now();
    let stalled = Arc::new(AtomicBool::new(false));
    let (tx, rx) = mpsc::channel::<Control>();
    // Pembaca stdin: EOF berarti induk mati, jadi keluar.
    thread::spawn(move || {
        let mut stdin = io::stdin().lock();
        loop {
            match read_frame(&mut stdin) {
                Ok(Frame::Control(c)) => {
                    if tx.send(c).is_err() {
                        return;
                    }
                }
                Ok(Frame::Audio { .. }) => {}
                Err(_) => {
                    let _ = tx.send(Control::Shutdown);
                    return;
                }
            }
        }
    });

    let mut out = io::stdout().lock();
    let send = |out: &mut io::StdoutLock, c: Control| write_frame(out, &Frame::Control(c)).is_ok();
    send(&mut out, Control::Hello { v: PROTOCOL_VERSION, binary: "recap-dummy-sidecar".into(), version: env!("CARGO_PKG_VERSION").into() });
    eprintln!("{{\"level\":\"info\",\"msg\":\"dummy sidecar siap\",\"pid\":{}}}", std::process::id());

    let mut frames_sent: u64 = 0;
    let mut seq: u32 = 0;
    let mut next_audio = Instant::now();
    let mut next_health = Instant::now() + Duration::from_secs(1);
    let pcm: Vec<u8> = (0..1600).flat_map(|i| ((i as f32 * 0.05).sin() * 0.1).to_le_bytes()).collect(); // 100 ms
    loop {
        match rx.recv_timeout(Duration::from_millis(20)) {
            Ok(Control::Ping { id }) if !stalled.load(Ordering::Relaxed) => {
                if !send(&mut out, Control::Pong { id }) {
                    return;
                }
            }
            Ok(Control::Crash) => {
                eprintln!("{{\"level\":\"warn\",\"msg\":\"crash diminta (abort)\"}}");
                let _ = io::stderr().flush();
                std::process::abort();
            }
            Ok(Control::Stall) => stalled.store(true, Ordering::Relaxed),
            Ok(Control::Shutdown) => return,
            _ => {}
        }
        if stalled.load(Ordering::Relaxed) {
            continue; // macet: tidak mengirim apa pun
        }
        if Instant::now() >= next_audio {
            let header = AudioHeader { version: 1, channel: 2, format: 0, channels: 1, sample_rate: 16_000, seq,
                                       sample_start: seq as u64 * 1600, host_time_ns: started.elapsed().as_nanos() as u64, payload_len: 0 };
            if write_frame(&mut out, &Frame::Audio { header, pcm: pcm.clone() }).is_err() {
                return;
            }
            seq += 1;
            frames_sent += 1;
            next_audio += Duration::from_millis(100);
        }
        if Instant::now() >= next_health {
            if !send(&mut out, Control::Health { uptime_ms: started.elapsed().as_millis() as u64, frames_sent }) {
                return;
            }
            next_health += Duration::from_secs(1);
        }
    }
}
