//! Uji host + supervisor terhadap sidecar tiruan sungguhan (proses terpisah).

use std::path::PathBuf;
use std::sync::mpsc;
use std::time::{Duration, Instant};

use recap_sidecar::host::{HostConfig, HostEvent, SidecarHost, SidecarSpec};
use recap_sidecar::Control;

fn spec() -> SidecarSpec {
    SidecarSpec { name: "dummy".into(), path: PathBuf::from(env!("CARGO_BIN_EXE_recap-dummy-sidecar")), args: vec![] }
}

fn fast_cfg() -> HostConfig {
    HostConfig {
        backoff: vec![Duration::from_millis(100)],
        max_restarts: 3,
        handshake_timeout: Duration::from_secs(3),
        ping_interval: Duration::from_millis(200),
        ping_timeout: Duration::from_millis(800),
        stable_after: Duration::from_secs(60),
    }
}

fn wait_for(rx: &mpsc::Receiver<HostEvent>, timeout: Duration, mut pred: impl FnMut(&HostEvent) -> bool) -> Vec<HostEvent> {
    let deadline = Instant::now() + timeout;
    let mut seen = vec![];
    while Instant::now() < deadline {
        if let Ok(ev) = rx.recv_timeout(Duration::from_millis(50)) {
            let hit = pred(&ev);
            seen.push(ev);
            if hit {
                return seen;
            }
        }
    }
    panic!("kondisi tidak terpenuhi dalam {timeout:?}; event: {seen:#?}");
}

#[test]
fn handshake_ping_dan_audio() {
    let (tx, rx) = mpsc::channel();
    let host = SidecarHost::spawn(spec(), fast_cfg(), move |e| { let _ = tx.send(e); });
    wait_for(&rx, Duration::from_secs(5), |e| matches!(e, HostEvent::Ready { .. }));
    wait_for(&rx, Duration::from_secs(5), |e| matches!(e, HostEvent::Pong { rtt, .. } if *rtt < Duration::from_millis(200)));
    wait_for(&rx, Duration::from_secs(5), |e| matches!(e, HostEvent::Audio { bytes: 6400, header } if header.sample_rate == 16_000));
    host.stop();
}

#[test]
fn crash_dipulihkan_dengan_restart() {
    let (tx, rx) = mpsc::channel();
    let host = SidecarHost::spawn(spec(), fast_cfg(), move |e| { let _ = tx.send(e); });
    wait_for(&rx, Duration::from_secs(5), |e| matches!(e, HostEvent::Ready { .. }));
    host.send(Control::Crash);
    wait_for(&rx, Duration::from_secs(5), |e| matches!(e, HostEvent::Exited { .. }));
    wait_for(&rx, Duration::from_secs(5), |e| matches!(e, HostEvent::Restarting { attempt: 1, .. }));
    wait_for(&rx, Duration::from_secs(5), |e| matches!(e, HostEvent::Ready { .. }));
    host.stop();
}

#[test]
fn macet_dideteksi_lewat_ping_lalu_restart() {
    let (tx, rx) = mpsc::channel();
    let host = SidecarHost::spawn(spec(), fast_cfg(), move |e| { let _ = tx.send(e); });
    wait_for(&rx, Duration::from_secs(5), |e| matches!(e, HostEvent::Ready { .. }));
    host.send(Control::Stall);
    let seen = wait_for(&rx, Duration::from_secs(5), |e| matches!(e, HostEvent::Exited { reason } if reason.contains("macet")));
    assert!(seen.iter().any(|e| matches!(e, HostEvent::Exited { .. })));
    wait_for(&rx, Duration::from_secs(5), |e| matches!(e, HostEvent::Ready { .. }));
    host.stop();
}

#[test]
fn circuit_breaker_menyerah_setelah_crash_beruntun() {
    let (tx, rx) = mpsc::channel();
    let host = SidecarHost::spawn(spec(), fast_cfg(), move |e| { let _ = tx.send(e); });
    let mut readies = 0;
    let deadline = Instant::now() + Duration::from_secs(20);
    loop {
        assert!(Instant::now() < deadline, "tidak menyerah dalam 20 s");
        match rx.recv_timeout(Duration::from_millis(50)) {
            Ok(HostEvent::Ready { .. }) => {
                readies += 1;
                host.send(Control::Crash);
            }
            Ok(HostEvent::GaveUp { reason }) => {
                assert!(reason.contains("restart"), "{reason}");
                break;
            }
            _ => {}
        }
    }
    assert_eq!(readies, 4, "1 start awal + 3 restart, lalu menyerah");
    host.stop();
}

#[test]
fn berhenti_rapi_tanpa_proses_yatim() {
    let (tx, rx) = mpsc::channel();
    let host = SidecarHost::spawn(spec(), fast_cfg(), move |e| { let _ = tx.send(e); });
    let pid = match wait_for(&rx, Duration::from_secs(5), |e| matches!(e, HostEvent::Spawned { .. })).pop() {
        Some(HostEvent::Spawned { pid, .. }) => pid,
        _ => unreachable!(),
    };
    wait_for(&rx, Duration::from_secs(5), |e| matches!(e, HostEvent::Ready { .. }));
    let t = Instant::now();
    host.stop();
    assert!(t.elapsed() < Duration::from_secs(3), "stop terlalu lama");
    // Proses sidecar sudah tidak ada.
    let out = std::process::Command::new("tasklist").args(["/FI", &format!("PID eq {pid}"), "/NH"]).output().unwrap();
    assert!(!String::from_utf8_lossy(&out.stdout).contains(&pid.to_string()), "sidecar {pid} masih hidup");
}
