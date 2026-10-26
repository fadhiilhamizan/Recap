//! Proses utama Recap (kerangka spike S8): supervisi sidecar, status ke UI lewat event,
//! command bertipe (tauri-specta), dan pengukuran waktu startup.

use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};
use std::time::Instant;

use recap_sidecar::host::{HostConfig, HostEvent, SidecarHost, SidecarSpec};
use recap_sidecar::Control;
use serde::Serialize;
use specta::Type;
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_specta::{collect_commands, Builder};

static PROCESS_START: OnceLock<Instant> = OnceLock::new();

/// Status sidecar yang ditampilkan UI. Proses utama adalah satu-satunya pemilik data ini.
#[derive(Clone, Debug, Default, Serialize, Type)]
pub struct SidecarStatus {
    pub state: String,
    pub pid: Option<u32>,
    pub restarts: u32,
    pub last_rtt_ms: Option<f64>,
    /// u32: specta menolak u64 ke TypeScript (presisi number JS hilang di atas 2^53).
    pub audio_frames: u32,
    pub last_event: String,
    pub binary_version: Option<String>,
}

#[derive(Clone, Debug, Serialize, Type)]
pub struct AppInfo {
    pub version: String,
    pub startup_ms: Option<f64>,
}

struct AppState {
    status: Mutex<SidecarStatus>,
    host: Mutex<Option<SidecarHost>>,
    startup_ms: Mutex<Option<f64>>,
}

fn sidecar_path(name: &str) -> PathBuf {
    // Tauri meletakkan `externalBin` di samping exe utama tanpa sufiks target triple.
    let exe = std::env::current_exe().expect("current_exe");
    exe.parent().unwrap().join(format!("{name}{}", std::env::consts::EXE_SUFFIX))
}

fn apply(status: &mut SidecarStatus, ev: &HostEvent) {
    match ev {
        HostEvent::Spawned { pid, .. } => {
            status.state = "starting".into();
            status.pid = Some(*pid);
        }
        HostEvent::Ready { version, .. } => {
            status.state = "running".into();
            status.binary_version = Some(version.clone());
        }
        HostEvent::Pong { rtt, .. } => status.last_rtt_ms = Some(rtt.as_secs_f64() * 1000.0),
        HostEvent::Audio { .. } => status.audio_frames = status.audio_frames.saturating_add(1),
        HostEvent::Exited { reason } => {
            status.state = "exited".into();
            status.last_event = reason.clone();
        }
        HostEvent::Restarting { attempt, delay } => {
            status.state = "restarting".into();
            status.restarts = *attempt;
            status.last_event = format!("restart ke-{attempt} dalam {:.1} s", delay.as_secs_f64());
        }
        HostEvent::GaveUp { reason } => {
            status.state = "failed".into();
            status.last_event = reason.clone();
        }
        HostEvent::Stopped => status.state = "stopped".into(),
        HostEvent::Control(_) | HostEvent::Log(_) => {}
    }
}

fn start_sidecar(app: &AppHandle) {
    let spec = SidecarSpec { name: "dummy".into(), path: sidecar_path("recap-dummy-sidecar"), args: vec![] };
    let handle = app.clone();
    let host = SidecarHost::spawn(spec, HostConfig::default(), move |ev| {
        let state = handle.state::<AppState>();
        let snapshot = {
            let mut s = state.status.lock().unwrap();
            apply(&mut s, &ev);
            s.clone()
        };
        // Frame audio terlalu sering untuk dikirim satu per satu ke UI; status lain dikirim segera.
        let noisy = matches!(ev, HostEvent::Audio { .. });
        if !noisy || snapshot.audio_frames % 10 == 0 {
            let _ = handle.emit("sidecar-status", snapshot);
        }
        if let HostEvent::Log(line) = ev {
            eprintln!("[sidecar] {line}");
        }
    });
    *app.state::<AppState>().host.lock().unwrap() = Some(host);
}

#[tauri::command]
#[specta::specta]
fn get_status(state: State<'_, AppState>) -> SidecarStatus {
    state.status.lock().unwrap().clone()
}

#[tauri::command]
#[specta::specta]
fn crash_sidecar(state: State<'_, AppState>) {
    if let Some(h) = state.host.lock().unwrap().as_ref() {
        h.send(Control::Crash);
    }
}

#[tauri::command]
#[specta::specta]
fn stall_sidecar(state: State<'_, AppState>) {
    if let Some(h) = state.host.lock().unwrap().as_ref() {
        h.send(Control::Stall);
    }
}

/// Dipanggil UI saat sudah tampil: mengukur waktu dari proses mulai sampai UI siap.
#[tauri::command]
#[specta::specta]
fn ui_ready(app: AppHandle, state: State<'_, AppState>) -> AppInfo {
    let ms = PROCESS_START.get().map(|t| t.elapsed().as_secs_f64() * 1000.0);
    let mut slot = state.startup_ms.lock().unwrap();
    if slot.is_none() {
        *slot = ms;
        if let (Some(ms), Ok(dir)) = (ms, app.path().app_log_dir()) {
            let _ = std::fs::create_dir_all(&dir);
            let line = format!("{{\"version\":\"{}\",\"startup_ms\":{ms:.0}}}\n", app.package_info().version);
            let _ = std::fs::OpenOptions::new().create(true).append(true).open(dir.join("startup.jsonl"))
                .and_then(|mut f| std::io::Write::write_all(&mut f, line.as_bytes()));
        }
    }
    AppInfo { version: app.package_info().version.to_string(), startup_ms: *slot }
}

fn builder() -> Builder<tauri::Wry> {
    Builder::<tauri::Wry>::new().commands(collect_commands![get_status, crash_sidecar, stall_sidecar, ui_ready])
}

/// Tulis ulang binding TypeScript dari tipe Rust (dijalankan di build debug).
pub fn export_bindings(path: &str) {
    builder()
        .export(specta_typescript::Typescript::default().header("// @ts-nocheck\n// Dibuat otomatis oleh tauri-specta. Jangan diedit.\n"), path)
        .expect("ekspor binding TypeScript");
}

pub fn run() {
    PROCESS_START.get_or_init(Instant::now);
    let builder = builder();
    #[cfg(debug_assertions)]
    export_bindings("../src/bindings.ts");

    tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .manage(AppState { status: Mutex::new(SidecarStatus { state: "init".into(), ..Default::default() }), host: Mutex::new(None), startup_ms: Mutex::new(None) })
        .invoke_handler(builder.invoke_handler())
        .setup(move |app| {
            builder.mount_events(app);
            start_sidecar(app.handle());
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                // Hentikan sidecar dengan rapi agar tidak ada proses yatim.
                if let Some(h) = window.state::<AppState>().host.lock().unwrap().take() {
                    h.stop();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("menjalankan aplikasi Tauri");
}
