# Spike S8: Kerangka Aplikasi Tauri, Sidecar, Packaging, dan Auto-Update (Windows)

Status: **Lulus**, kecuali code signing Windows (menunggu pendaftaran SignPath) · Dijalankan: 2026-10-26

## 1. Yang dibangun

| Komponen | Lokasi | Isi |
|---|---|---|
| Workspace Cargo | `Cargo.toml` (root) | `apps/desktop/src-tauri`, `crates/recap-sidecar`, `crates/recap-dummy-sidecar` (prototipe spike dikecualikan) |
| Protokol + host sidecar | `crates/recap-sidecar` | Frame stdio (`u32` panjang + `u8` jenis + payload; JSON control atau audio dengan header 32 byte), batas ukuran frame, handshake `hello` + cek versi protokol, ping/pong, restart dengan backoff 1/2/4/8/10 detik, circuit breaker (5 restart beruntun), reset setelah stabil 60 detik, berhenti rapi (shutdown, tunggu 1,5 detik, lalu kill) |
| Sidecar tiruan | `crates/recap-dummy-sidecar` | Hello, pong, frame audio palsu 16 kHz tiap 100 ms, health tiap detik, perintah crash (abort) dan macet; keluar saat stdin ditutup |
| Proses utama Tauri 2 | `apps/desktop/src-tauri` | Supervisi sidecar, status ke UI lewat event, command bertipe (tauri-specta), pengukuran waktu startup ke `startup.jsonl`, plugin updater + process, CSP ketat, capability minimal (tanpa shell/filesystem dari WebView) |
| UI | `apps/desktop/src` | React 19 + Vite 8 + TypeScript 7, i18n id/en (i18next), status sidecar, tombol simulasi crash/macet, cek pembaruan |
| Binding TS | `apps/desktop/src/bindings.ts` | Dibuat otomatis: `cargo run -p recap-app --features bindgen --bin export-bindings` |
| Uji update | `tools/spikes/s8-update/update_test.ps1` | Langkah uji update lokal (lihat catatan di bagian 4) |

Versi (dicek 2026-10-26): Tauri 2.12.5, tauri-build 2.7.4, tauri-plugin-updater 2.14.0, tauri-plugin-process 2.4.0, **tauri-specta 2.0.0-rc.26** (pre-release; versi 1.0.2 hanya untuk Tauri 1), Rust 1.99, Node 24.

## 2. Hasil uji

### 2.1 Uji otomatis (`cargo test -p recap-sidecar -p recap-dummy-sidecar`)

| Uji | Hasil |
|---|---|
| Golden frame control dan header audio (format kabel dikunci) | Lulus |
| Roundtrip frame, EOF, dan panjang frame rusak ditolak (tidak dialokasikan) | Lulus |
| Handshake + ping (RTT di bawah 200 ms) + frame audio diterima | Lulus |
| Crash sidecar (abort): terdeteksi, restart, ready kembali | Lulus |
| Sidecar macet: terdeteksi lewat ping timeout, dibunuh, restart | Lulus |
| Circuit breaker: setelah 3 restart beruntun (konfigurasi uji), menyerah dengan pesan jelas | Lulus |
| Berhenti rapi di bawah 3 detik, **tanpa proses sidecar yatim** | Lulus |

### 2.2 Packaging dan instalasi (NSIS, per-user)

| Kriteria (dokumen 10) | Target | Hasil |
|---|---|---|
| Installer berjalan di mesin | Ya | Lulus: install silent `/S` ke `%LOCALAPPDATA%\Recap Dev`, uninstall silent bersih (folder, proses, entri registry) |
| Ukuran installer (tanpa ffmpeg dan model) | Di bawah 30 MB | **3,05 MB** |
| Startup sampai UI siap | 3 detik atau kurang | **604 ms** (pertama kali setelah install) / **332 sampai 333 ms** (berikutnya) |
| Sidecar spawn dari bundle | Ya | Lulus: `recap-dummy-sidecar.exe` di samping exe utama, tanpa jendela konsol |
| Crash sidecar dipulihkan | Ya | Lulus (uji otomatis + tombol simulasi di UI) |
| Waktu build release | n/a | Sekitar 3 menit build bersih; build ulang sekitar 1 sampai 2 menit |

### 2.3 Auto-update (feed lokal `http://127.0.0.1:8777`)

| Skenario | Hasil |
|---|---|
| v0.0.1 terpasang, feed menawarkan v0.0.2 yang ditandatangani | **Lulus**: cek, unduh, verifikasi signature minisign, pasang (passive), dan restart **dalam sekitar 5 detik**; v0.0.2 berjalan dengan satu sidecar, tanpa proses lama tersisa |
| Feed menawarkan "v0.0.3" dengan signature yang tidak cocok dengan file | **Lulus (ditolak)**: installer diunduh tetapi **tidak dipasang**; aplikasi tetap v0.0.1 dan terus berjalan |

## 3. Temuan dan pelajaran

1. **Bundler Tauri menyertakan semua biner paket.** Biner utilitas (generator binding) ikut masuk installer. Solusinya, utilitas dibuat `required-features` sehingga tidak dibangun saat `tauri build`.
2. **Biner uji yang me-link Tauri gagal di Windows** dengan `0xC0000139` karena tidak mendapat manifest Common Controls v6. Jangan menaruh uji yang me-link Tauri di crate aplikasi. Logika yang perlu diuji ditempatkan di crate tanpa Tauri (`recap-sidecar`, `recap-store`, dan seterusnya), dan ini sejalan dengan desain monorepo dokumen 03.
3. **specta menolak `u64` ke TypeScript** (presisi `number` JS hilang di atas 2^53). Ini pengaman yang bagus: penghitung yang dikirim ke UI memakai `u32`, atau string untuk ID besar.
4. **PowerShell 5.1:** `Set-Content -Encoding utf8` menulis BOM sehingga `tauri.conf.json` gagal diparsing; stderr program native dianggap error. Skrip build memakai `[IO.File]::WriteAllText` tanpa BOM, dan `cmd /c` untuk perintah native.
5. **Uninstaller NSIS default mempertahankan data aplikasi** (`%LOCALAPPDATA%\id.recap.dev`). Untuk Recap ini keputusan UX penting (berisi rekaman). Rekomendasinya: pertahankan secara default, dan sediakan opsi "hapus juga data saya" di uninstaller dan di Pengaturan.
6. **Restart oleh updater menutup sidecar dengan benar**, karena hook `WindowEvent::Destroyed` menghentikan host. Untuk `recap-capture` nanti, update harus **ditunda selama rekaman berlangsung**.

## 4. Yang belum selesai / sebelum rilis

| Item | Status | Tindakan |
|---|---|---|
| Code signing Windows (SignPath Foundation) | **Belum** | Repo `fadhiilhamizan/Recap` sudah publik. Pemilik proyek perlu menambahkan file LICENSE (ADR-021: MIT OR Apache-2.0), lalu mendaftar di signpath.org. Selama itu installer belum ditandatangani, sehingga SmartScreen akan memperingatkan |
| Feed update produksi | Belum | Ganti endpoint ke HTTPS (GitHub Releases `latest.json`) dan matikan `dangerousInsecureTransportProtocol` |
| Kunci updater | Kunci **dev** di `.data/keys` (tidak di-commit) | Buat kunci produksi terpisah, simpan sebagai secret CI (environment terlindungi), dan ganti `pubkey` |
| CI build Windows | Belum | GitHub Actions `windows-latest`: build sidecar, `tauri build`, artefak, signing (setelah SignPath) |
| Uji di Windows 10 bersih (VM) | Belum | Termasuk ketersediaan WebView2 (bootstrapper NSIS) |
| Skrip `update_test.ps1` | Ditulis | Menjalankan `.ps1` butuh kebijakan eksekusi yang mengizinkan skrip lokal. Uji di atas dijalankan langkah demi langkah sebagai perintah biasa, **tanpa** melemahkan kebijakan eksekusi |
