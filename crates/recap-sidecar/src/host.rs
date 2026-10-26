//! Host sidecar: spawn proses anak, handshake, ping/pong, dan restart dengan backoff
//! (dokumen 03 bagian 4.3). Satu thread supervisor per sidecar; tidak bergantung pada Tauri.

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use crate::protocol::{read_frame, write_frame, AudioHeader, Control, Frame, FrameError, PROTOCOL_VERSION};

#[derive(Clone, Debug)]
pub struct SidecarSpec {
    pub name: String,
    pub path: PathBuf,
    pub args: Vec<String>,
}

#[derive(Clone, Debug)]
pub struct HostConfig {
    pub backoff: Vec<Duration>,
    /// Restart beruntun maksimum sebelum menyerah (circuit breaker).
    pub max_restarts: u32,
    pub handshake_timeout: Duration,
    pub ping_interval: Duration,
    /// Tidak ada pong selama ini: sidecar dianggap macet lalu dibunuh.
    pub ping_timeout: Duration,
    /// Berjalan stabil selama ini: hitungan restart direset.
    pub stable_after: Duration,
}

impl Default for HostConfig {
    fn default() -> Self {
        Self {
            backoff: [1, 2, 4, 8, 10].into_iter().map(Duration::from_secs).collect(),
            max_restarts: 5,
            handshake_timeout: Duration::from_secs(5),
            ping_interval: Duration::from_secs(1),
            ping_timeout: Duration::from_secs(3),
            stable_after: Duration::from_secs(60),
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum HostEvent {
    Spawned { pid: u32, attempt: u32 },
    Ready { binary: String, version: String },
    Pong { id: u64, rtt: Duration },
    Control(Control),
    Audio { header: AudioHeader, bytes: usize },
    Log(String),
    Exited { reason: String },
    Restarting { attempt: u32, delay: Duration },
    GaveUp { reason: String },
    Stopped,
}

enum Cmd {
    Send(Control),
    Stop,
}

pub struct SidecarHost {
    tx: Sender<Cmd>,
    join: Option<JoinHandle<()>>,
}

impl SidecarHost {
    pub fn spawn(spec: SidecarSpec, cfg: HostConfig, on_event: impl Fn(HostEvent) + Send + 'static) -> Self {
        let (tx, rx) = mpsc::channel();
        let join = thread::Builder::new()
            .name(format!("sidecar-{}", spec.name))
            .spawn(move || supervise(spec, cfg, rx, on_event))
            .expect("thread supervisor");
        Self { tx, join: Some(join) }
    }

    pub fn send(&self, c: Control) {
        let _ = self.tx.send(Cmd::Send(c));
    }

    pub fn stop(mut self) {
        let _ = self.tx.send(Cmd::Stop);
        if let Some(j) = self.join.take() {
            let _ = j.join();
        }
    }
}

impl Drop for SidecarHost {
    fn drop(&mut self) {
        let _ = self.tx.send(Cmd::Stop);
        if let Some(j) = self.join.take() {
            let _ = j.join();
        }
    }
}

enum Incoming {
    Frame(Frame),
    Closed(String),
}

fn start(spec: &SidecarSpec) -> std::io::Result<(Child, ChildStdin, Receiver<Incoming>, Receiver<String>)> {
    let mut cmd = Command::new(&spec.path);
    cmd.args(&spec.args).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW: tanpa jendela konsol
    }
    let mut child = cmd.spawn()?;
    let stdin = child.stdin.take().unwrap();
    let mut stdout = child.stdout.take().unwrap();
    let stderr = child.stderr.take().unwrap();
    let (ftx, frx) = mpsc::channel();
    thread::spawn(move || loop {
        match read_frame(&mut stdout) {
            Ok(f) => {
                if ftx.send(Incoming::Frame(f)).is_err() {
                    return;
                }
            }
            Err(FrameError::Eof) => {
                let _ = ftx.send(Incoming::Closed("stdout ditutup".into()));
                return;
            }
            Err(e) => {
                let _ = ftx.send(Incoming::Closed(format!("frame rusak: {e}")));
                return;
            }
        }
    });
    let (ltx, lrx) = mpsc::channel();
    thread::spawn(move || {
        for line in BufReader::new(stderr).lines().map_while(Result::ok) {
            if ltx.send(line).is_err() {
                return;
            }
        }
    });
    Ok((child, stdin, frx, lrx))
}

fn kill(child: &mut Child) {
    let _ = child.kill();
    let _ = child.wait();
}

fn supervise(spec: SidecarSpec, cfg: HostConfig, rx: Receiver<Cmd>, emit: impl Fn(HostEvent)) {
    let mut restarts: u32 = 0;
    let mut attempt: u32 = 0;
    'outer: loop {
        let (mut child, mut stdin, frames, logs) = match start(&spec) {
            Ok(x) => x,
            Err(e) => {
                emit(HostEvent::GaveUp { reason: format!("gagal menjalankan {}: {e}", spec.path.display()) });
                return;
            }
        };
        emit(HostEvent::Spawned { pid: child.id(), attempt });
        let started = Instant::now();
        let mut ready = false;
        let mut next_ping = Instant::now() + cfg.ping_interval;
        let mut ping_id: u64 = 0;
        let mut pending_ping: Option<(u64, Instant)> = None;
        let exit_reason: String = loop {
            // Perintah dari aplikasi.
            match rx.try_recv() {
                Ok(Cmd::Send(c)) => {
                    let _ = write_frame(&mut stdin, &Frame::Control(c));
                }
                Ok(Cmd::Stop) | Err(mpsc::TryRecvError::Disconnected) => {
                    let _ = write_frame(&mut stdin, &Frame::Control(Control::Shutdown));
                    drop(stdin);
                    let deadline = Instant::now() + Duration::from_millis(1500);
                    while Instant::now() < deadline {
                        if let Ok(Some(_)) = child.try_wait() {
                            break;
                        }
                        thread::sleep(Duration::from_millis(50));
                    }
                    kill(&mut child);
                    emit(HostEvent::Stopped);
                    return;
                }
                Err(mpsc::TryRecvError::Empty) => {}
            }
            for line in logs.try_iter() {
                emit(HostEvent::Log(line));
            }
            // Frame dari sidecar.
            match frames.recv_timeout(Duration::from_millis(50)) {
                Ok(Incoming::Frame(Frame::Control(Control::Hello { v, binary, version }))) => {
                    if v != PROTOCOL_VERSION {
                        kill(&mut child);
                        emit(HostEvent::GaveUp { reason: format!("versi protokol {v} tidak cocok (host {PROTOCOL_VERSION}); instalasi rusak?") });
                        return;
                    }
                    ready = true;
                    emit(HostEvent::Ready { binary, version });
                }
                Ok(Incoming::Frame(Frame::Control(Control::Pong { id }))) => {
                    if let Some((pid, t)) = pending_ping {
                        if pid == id {
                            emit(HostEvent::Pong { id, rtt: t.elapsed() });
                            pending_ping = None;
                        }
                    }
                }
                Ok(Incoming::Frame(Frame::Control(c))) => emit(HostEvent::Control(c)),
                Ok(Incoming::Frame(Frame::Audio { header, pcm })) => emit(HostEvent::Audio { header, bytes: pcm.len() }),
                Ok(Incoming::Closed(why)) => break why,
                Err(RecvTimeoutError::Timeout) => {}
                Err(RecvTimeoutError::Disconnected) => break "pembaca berhenti".into(),
            }
            if !ready && started.elapsed() > cfg.handshake_timeout {
                break "tidak ada hello dalam batas waktu".into();
            }
            if ready && Instant::now() >= next_ping {
                if let Some((_, t)) = pending_ping {
                    if t.elapsed() > cfg.ping_timeout {
                        break format!("tidak menjawab ping selama {:.1} s (macet)", t.elapsed().as_secs_f64());
                    }
                } else {
                    ping_id += 1;
                    pending_ping = Some((ping_id, Instant::now()));
                    if write_frame(&mut stdin, &Frame::Control(Control::Ping { id: ping_id })).is_err() {
                        break "stdin ditutup".into();
                    }
                }
                next_ping = Instant::now() + cfg.ping_interval;
            }
        };
        kill(&mut child);
        let code = child.try_wait().ok().flatten().and_then(|s| s.code());
        emit(HostEvent::Exited { reason: format!("{exit_reason} (kode keluar {code:?})") });

        if started.elapsed() >= cfg.stable_after {
            restarts = 0;
        }
        if restarts >= cfg.max_restarts {
            emit(HostEvent::GaveUp { reason: format!("{} restart beruntun; berhenti mencoba", restarts) });
            return;
        }
        let delay = cfg.backoff[(restarts as usize).min(cfg.backoff.len() - 1)];
        restarts += 1;
        attempt += 1;
        emit(HostEvent::Restarting { attempt, delay });
        // Tunggu backoff, tapi tetap responsif terhadap Stop.
        let until = Instant::now() + delay;
        while Instant::now() < until {
            match rx.recv_timeout(Duration::from_millis(50)) {
                Ok(Cmd::Stop) | Err(RecvTimeoutError::Disconnected) => {
                    emit(HostEvent::Stopped);
                    break 'outer;
                }
                _ => {}
            }
        }
    }
}
