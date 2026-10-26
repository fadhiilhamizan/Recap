//! Tulis ulang `src/bindings.ts` dari tipe Rust:
//! `cargo run -p recap-app --features bindgen --bin export-bindings`.
//!
//! Dibuat sebagai biner (bukan uji) karena biner uji Tauri di Windows tidak mendapat manifest
//! Common Controls v6 dan gagal dengan 0xC0000139 (STATUS_ENTRYPOINT_NOT_FOUND).

fn main() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../src/bindings.ts");
    recap_app_lib::export_bindings(path);
    let ts = std::fs::read_to_string(path).expect("baca bindings.ts");
    for name in ["getStatus", "crashSidecar", "stallSidecar", "uiReady", "SidecarStatus", "AppInfo"] {
        assert!(ts.contains(name), "binding tidak memuat {name}");
    }
    println!("binding ditulis: {path}");
}
