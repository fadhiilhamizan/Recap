# 04. Keputusan Teknologi (Architecture Decision Records)

Setiap ADR memuat konteks, opsi, kriteria, perbandingan, keputusan, konsekuensi, dan cara validasi. Semua status **Diusulkan**, sampai dibuktikan oleh spike di dokumen 10, lalu disetujui.

## Konteks yang mengikat (hasil klarifikasi 2026-10-08)

- **Lisensi:** proyek open source.
- **Target OS MVP:** Windows 10 2004+/11 x64 dan macOS 14.2+ Apple Silicon. Linux menyusul setelah MVP.
- **Perangkat minimum:** RAM 8 GB tanpa GPU (mode hemat); 16 GB atau GPU disarankan.
- **Stack:** Tauri 2 + Rust.
- **Tim:** solo, paruh waktu.
- **Mode transkripsi:** hybrid, yaitu draf live ditambah final pass.
- **MVP ramping.**
- **Cloud BYOK:** opsional, mati secara default.

## Skala penilaian

| Simbol | Arti |
|---|---|
| `++` | Sangat baik |
| `+` | Baik |
| `0` | Netral |
| `-` | Kurang |
| `--` | Buruk |

Bobot kriteria ditulis dalam kurung, misalnya (3) berarti sangat penting.

## Daftar ADR

| No | Keputusan | Rekomendasi singkat |
|---|---|---|
| 001 | Framework desktop | Tauri 2 |
| 002 | Bahasa backend | Rust |
| 003 | Model proses dan IPC | Proses utama + 3 sidecar Rust, IPC stdio berbingkai |
| 004 | Capture audio Windows | WASAPI process loopback EXCLUDE (crate `wasapi`), fallback endpoint loopback |
| 005 | Capture audio macOS | Core Audio process tap (cidre / Swift kecil), fallback ScreenCaptureKit (pasca-MVP) |
| 006 | Capture audio Linux | PipeWire, fallback PulseAudio monitor (pasca-MVP) |
| 007 | Format dan strategi penyimpanan audio | WAV 16-bit per kanal berchunk, flush 1 detik, lalu arsip Ogg Opus |
| 008 | Echo cancellation dan sinkronisasi | WebRTC AEC3 di jalur STT, timestamp per buffer + resampler drift |
| 009 | Runtime STT | Abstraksi engine; whisper.cpp (default) + transcribe.cpp (Qwen3-ASR) setelah spike |
| 010 | Model STT default per tier | Final: Qwen3-ASR-1.7B / large-v3-turbo; draf: Qwen3-ASR-0.6B / Whisper small |
| 011 | VAD | Silero VAD v6 (ONNX) |
| 012 | Diarization | MVP: per kanal. Beta: sherpa-onnx offline |
| 013 | Runtime LLM | llama.cpp tertanam (llama-cpp-2) + provider eksternal |
| 014 | Model LLM default | Qwen3.5-4B (8 GB), Qwen3.5-9B (16 GB), Gemma 4 12B alternatif |
| 015 | Database dan pencarian | SQLite WAL (rusqlite) + FTS5 unicode61 + sqlite-vec (Beta) |
| 016 | Model embedding | Qwen3-Embedding-0.6B, fallback multilingual-e5-small |
| 017 | Downloader URL | yt-dlp sidecar on-demand + auto-update (Beta, eksperimental) |
| 018 | Decoder file | ffmpeg LGPL sidecar |
| 019 | Stack UI | React + TypeScript + Vite + Tailwind + i18next + tauri-specta |
| 020 | Distribusi, signing, update | tauri-plugin-updater + GitHub Releases; SignPath (Win); Developer ID (mac) |
| 021 | Lisensi proyek | MIT OR Apache-2.0 |
| 022 | Rahasia dan provider cloud | Keychain OS; adapter OpenAI-compatible + Anthropic + Gemini + Deepgram |
| 023 | Ekspor dokumen | Markdown/SRT/VTT (MVP); DOCX via docx-rs, PDF via Typst (Beta) |

---

## ADR-001: Framework desktop

**Konteks.** Recap memproses audio real-time dan model ML berat, harus ringan, dan dikerjakan solo. Ini sudah dipilih pengguna saat klarifikasi; ADR ini mencatat alasannya.

| Kriteria (bobot) | Tauri 2 | Electron 44 | Flutter | Qt 6 (C++/QML) |
|---|---|---|---|---|
| Akses native audio/ML (3) | `++` Rust in-process: cpal, wasapi, cidre, whisper-rs, ort | `+` lewat addon N-API atau helper | `-` ekosistem loopback desktop tipis | `++` |
| Ukuran dan RAM (2) | `++` installer inti sekitar <10 MB | `-` sekitar 80 sampai 150 MB, RAM sekitar 130 sampai 300 MB | `+` | `+` |
| Konsistensi UI lintas OS (1) | `-` WebView2 / WKWebView / WebKitGTK berbeda | `++` Chromium sama | `++` | `+` |
| Produktivitas UI (2) | `++` React | `++` React | `+` | `-` |
| Kode referensi yang relevan (2) | `++` meetily, Anarlog, Handy, Vibe | `+` prismical, OpenWhispr | `--` | `-` |
| Risiko (2) | `0` bug WebView spesifik OS; harus belajar Rust | `0` ABI addon per versi Electron | `-` | `-` lisensi LGPL/komersial |

Versi dicek 2026-10-08: Tauri **v2.12.1** (2026-09-30), Tauri v3.0.0-alpha.4 (2026-10-01, menambah runtime CEF opsional), Electron **v44.7.0** (2026-10-07).

**Keputusan:** Tauri 2 (rilis 2.x terbaru). Tauri v3 tidak dipakai sampai stabil, tetapi patut dipantau karena runtime CEF opsional bisa menghilangkan perbedaan WebView.

**Konsekuensi:**
- Harus menguji UI di WebView2 dan WKWebView. Linux (WebKitGTK) paling lemah dan baru dikerjakan pasca-MVP.
- Bergantung pada Rust; kurva belajar menjadi risiko jadwal untuk developer solo (lihat dokumen 09).

**Validasi:** spike S8 (kerangka aplikasi + sidecar + packaging).

---

## ADR-002: Bahasa backend

| Kriteria (bobot) | Rust | TypeScript (Node) | Python sidecar |
|---|---|---|---|
| Performa dan kontrol real-time (3) | `++` | `0` | `-` GIL, start lambat |
| Ekosistem audio/ML native (3) | `++` cpal, wasapi, cidre, whisper-rs, llama-cpp-2, sherpa-onnx, ort, rubato, webrtc-audio-processing | `+` lewat addon | `++` faster-whisper, pyannote, WhisperX |
| Packaging lintas OS (3) | `++` binary statis | `+` | `--` interpreter + torch, ratusan MB sampai GB, rawan |
| Produktivitas developer solo (2) | `0` | `++` | `+` |
| Satu bahasa untuk semua proses (1) | `++` | `0` | `-` |

**Keputusan:** Rust untuk proses utama dan semua sidecar. Python **tidak** dipakai di runtime aplikasi. Python boleh dipakai di **tooling evaluasi** (skrip benchmark WER/DER di folder `tools/`), bukan di produk.

**Konsekuensi:** Fitur yang hanya ada di Python (pyannote community-1, WhisperX alignment) tidak tersedia secara lokal. Gantinya sherpa-onnx (ONNX) atau provider cloud.

---

## ADR-003: Model proses dan IPC

**Konteks.**
- Crash native di STT (whisper/ggml) menjatuhkan seluruh meetily (issue #594, #698).
- Prismical memisahkan worker whisper ke proses lain, dan meetily memisahkan LLM ke `llama-helper`.
- Rekaman 2 sampai 3 jam harus tetap aman walau komponen lain gagal.

**Opsi:**
- **A. Semua in-process** (seperti meetily). Paling sederhana, tetapi crash native mematikan rekaman.
- **B. Proses utama + sidecar per area risiko.** Pembagiannya:
  - `recap-capture`: capture + penulisan audio
  - `recap-asr`: VAD + STT + diarization
  - `recap-llm`: LLM + embedding
- **C. Satu sidecar "engine" untuk semua ML** + capture in-process.

| Kriteria (bobot) | A | B | C |
|---|---|---|---|
| Isolasi crash (3) | `--` | `++` | `+` |
| Rekaman selamat bila ML crash (3) | `--` | `++` | `+` |
| Kompleksitas untuk solo dev (2) | `++` | `0` | `+` |
| Kontrol memori (bisa unload model dengan mematikan proses) (2) | `-` | `++` | `+` |
| Bisa dipakai sebagai CLI untuk spike dan tes (1) | `-` | `++` | `+` |

**Keputusan: Opsi B.** Semuanya binary Rust dari satu cargo workspace, dengan protokol bersama di crate `recap-protocol`.

**Desain IPC:**
- **UI ↔ proses utama:**
  - Tauri commands (request/response) dan Tauri events/Channel (stream: level meter, segmen live, progres job).
  - Tipe TypeScript dihasilkan otomatis dengan `tauri-specta` (v1.0.2, MIT, dicek 2026-10-08) agar kontrak tidak menyimpang.
  - UI **tidak pernah** memegang data primer.
- **Proses utama ↔ sidecar:** stdin/stdout dengan frame berprefiks panjang:
  - **JSON control:** perintah, event, dan error. Setiap pesan punya `id`, `type`, dan `v` (versi protokol).
  - **Audio:** frame biner dengan header tetap yang diadaptasi dari 32-byte header prismical (versi, kanal, format, sample rate, seq, sample_start, host_time_ns, panjang payload).
- **Log:** stderr berupa JSON lines, ditampung proses utama ke file log berotasi.
- **Kematian proses induk:** sidecar mendeteksinya dengan stdin EOF. `recap-capture` lalu menutup file audio dengan rapi sebelum keluar.
- **Supervisi:** proses utama me-restart sidecar dengan backoff eksponensial, maksimal 5 kali per sesi (pola prismical `RESTART_SCHEDULE`), dan memakai circuit breaker per rekaman untuk ASR.

**Konsekuensi:**
- Ada empat binary yang harus di-sign dan dinotarisasi. Di macOS, `NSMicrophoneUsageDescription` dan `NSAudioCaptureUsageDescription` dipasang di bundle aplikasi. Atribusi izin TCC untuk proses anak perlu diuji di spike S2 (**perlu diverifikasi**, walau prismical membuktikan pola ini berjalan dengan helper Swift).
- Audio live harus dikirim dari capture ke ASR (lihat dokumen 03).

---

## ADR-004: Capture audio Windows

| Kriteria (bobot) | A. Process loopback EXCLUDE PID Recap (crate `wasapi`) | B. Endpoint loopback default render (cpal/`wasapi`) | C. Electron/Chromium `getDisplayMedia` loopback | D. Driver virtual (VB-Cable) |
|---|---|---|---|---|
| Tidak menangkap suara Recap sendiri (2) | `++` | `-` | `0` | `-` |
| Tahan ganti device output (2) | `++` tidak terikat endpoint | `-` harus buka ulang stream | `0` | `-` |
| Versi OS (2) | `0` Win10 2004+ yang ter-update (dokumen resmi menyebut build 20348; **perlu diverifikasi** di spike) | `++` | `+` | `+` |
| Tanpa instalasi tambahan (3) | `++` | `++` | `++` | `--` |
| Kematangan (2) | `0` dipakai OBS dan OpenWhispr | `++` | `+` | `+` |

Crate: `wasapi` **0.25.0** (HEnquist, MIT, 2026-10-01) mendukung endpoint loopback dan application/process loopback (include/exclude tree).

**Keputusan:**
- **Sistem:** A sebagai jalur utama. B sebagai fallback otomatis bila aktivasi A gagal; B mengikuti perubahan device default (poll + 2 konfirmasi, pola Anarlog).
- **Mic:** WASAPI shared mode lewat `wasapi`, atau cpal bila lebih sederhana.

**Konsekuensi:**
- Loopback **tidak mengirim paket saat hening**, jadi capture harus mengisi celah dengan sunyi berdasarkan clock (QPC) agar timeline sinkron.
- Audio dari aplikasi exclusive mode dan konten ber-DRM tidak tertangkap. Panggilan Zoom/Meet/Teams normal tidak terdampak.
- Headset Bluetooth turun ke mode HFP saat mic-nya dipakai. UI harus memberi peringatan, dan Recap tidak boleh membuka mic Bluetooth yang tidak dipilih pengguna.

**Validasi:** spike S1.

---

## ADR-005: Capture audio macOS

| Kriteria (bobot) | A. Core Audio process tap (14.2+) | B. ScreenCaptureKit audio (13+) | C. Driver virtual (BlackHole) |
|---|---|---|---|
| Izin yang dibutuhkan (3) | `++` "System Audio Recording Only" | `-` Screen Recording (invasif, diminta ulang berkala di Sequoia) | `-` instal driver (admin) |
| Bisa exclude proses sendiri (2) | `++` | `+` `excludesCurrentProcessAudio` | `--` |
| Versi OS (2) | `0` 14.2+ (target MVP sesuai klarifikasi) | `+` | `++` |
| Bisa cek status izin (1) | `--` tidak ada API publik | `+` | n/a |
| Lisensi (1) | `++` | `++` | `--` GPL-3.0 |

**Implementasi.** Ada dua opsi:
1. Rust dengan `cidre` (MIT, dipakai meetily dan Anarlog; API sering berubah dan dokumentasinya minim).
2. Helper Swift kecil seperti prismical dan OpenWhispr. Meski ditulis dalam Swift, tetap memakai protokol `recap-protocol` yang sama.

Keduanya akan dicoba di spike S2. Kecenderungan awal adalah `cidre`, agar tetap satu bahasa. Bila API cidre bermasalah, pakai helper Swift.

**Keputusan:**
- **Sistem:** A untuk macOS 14.2+, dengan tap global mono yang mengecualikan PID proses Recap (termasuk sidecar).
- **Mic:** AVAudioEngine atau AudioUnit HAL lewat cpal. Hati-hati dengan error `-10863` di macOS 26 (prismical #21); uji di macOS 26.
- B (ScreenCaptureKit) dipertimbangkan pasca-MVP untuk macOS 13.x hanya bila ada permintaan. C hanya didokumentasikan sebagai cara manual.

**Konsekuensi:**
- Karena izin tap tidak bisa dicek, Recap mendeteksi "system audio sunyi total selama N detik saat ada aktivitas audio" lalu menampilkan panduan membuka System Settings.
- Izin TCC terikat code signature, sehingga uji izin harus memakai build yang di-sign Developer ID.
- Klaim bahwa izin di macOS 26 berubah berasal dari panduan pihak ketiga (**perlu diverifikasi**).

---

## ADR-006: Capture audio Linux (pasca-MVP)

| Opsi | Catatan |
|---|---|
| A. PipeWire native (capture stream ke monitor sink) | Modern; cpal 0.18 sudah punya host PipeWire. Pola Anarlog |
| B. PulseAudio `<default_sink>.monitor` | Berjalan juga lewat pipewire-pulse |
| C. ALSA berdasarkan nama "monitor" | Rapuh (meetily #701) |

**Keputusan:** A dengan fallback B. Distribusi lewat AppImage + deb lebih dulu, lalu Flatpak (`--socket=pulseaudio`). Belum ada portal izin audio di Linux.

---

## ADR-007: Format dan strategi penyimpanan audio

**Kebutuhan:**
- tahan crash dengan kehilangan maksimal sekitar 1 sampai 2 detik
- kanal terpisah
- bisa diputar ulang
- bisa ditranskripsi ulang
- hemat disk untuk 2 sampai 3 jam

| Kriteria (bobot) | A. WAV per kanal, chunk 5 menit, flush 1 detik, lalu arsip Opus | B. Ogg Opus streaming langsung | C. Checkpoint AAC 30 detik digabung (meetily) | D. FLAC streaming |
|---|---|---|---|---|
| Tahan crash (3) | `++` header bisa dipulihkan dari ukuran file | `+` per halaman Ogg | `0` kehilangan sampai 30 detik | `+` |
| CPU saat rekam (2) | `++` nol encode | `0` | `-` spawn ffmpeg tiap 30 detik | `0` |
| Disk saat rekam (1) | `-` sekitar 345 MB/jam/kanal (16-bit 48 kHz mono) | `++` | `++` | `+` |
| Disk arsip (2) | `++` Opus 24 sampai 32 kbps, sekitar 11 sampai 14 MB/jam/kanal | `++` | `+` | `0` |
| Kesederhanaan (2) | `++` | `0` | `-` | `0` |
| Kualitas untuk AEC/STT ulang (2) | `++` lossless sampai diarsipkan | `0` lossy | `0` | `++` |

**Keputusan:** A.
- **Saat rekam:** `meetings/<id>/audio/{mic,system}/NNNN.wav`, PCM 16-bit, 48 kHz mono, dipotong tiap 5 menit, flush tiap 1 detik. Ada file `timeline.jsonl` berisi host-time per blok untuk sinkronisasi.
- **Setelah final pass selesai:** dienkode ke `mic.opus` dan `system.opus` (Ogg Opus, via ffmpeg LGPL dengan libopus), lalu WAV dihapus sesuai kebijakan retensi (lihat dokumen 06).

**Konsekuensi:**
- Rekaman 3 jam butuh sekitar 2,1 GB disk sementara.
- Recap memeriksa ruang kosong sebelum mulai. Ambang awal: bila tersisa kurang dari 3 GB, rekam tetap jalan dengan peringatan; bila kurang dari 1 GB, tolak memulai.
- Playback setelah arsip memakai Opus. Re-transkripsi mendekode Opus, dengan sedikit penurunan kualitas yang dapat diterima.

---

## ADR-008: Echo cancellation dan sinkronisasi dua sumber

**Masalah:**
- Tanpa headset, mic menangkap ulang suara speaker. Akibatnya transkrip ganda, dan ucapan "peserta" tercatat sebagai "saya".
- Mic dan loopback berjalan di clock hardware berbeda, sehingga drift menumpuk selama 2 sampai 3 jam.

| Opsi AEC | Catatan |
|---|---|
| A. WebRTC AEC3 (crate `webrtc-audio-processing` 2.1.0, BSD-3, tonarino) | Terbukti di prismical. Referensi = system audio. Holdback mic sekitar 300 ms |
| B. speexdsp AEC | Ringan, kualitas lebih rendah |
| C. AEC neural ONNX (pola Anarlog) | Lebih berat dan butuh model |
| D. Tanpa AEC: dedup teks + anjuran headset | Paling sederhana dan rapuh |

**Keputusan:**
- **AEC:** A diterapkan **hanya di jalur STT** (mic hasil AEC dikirim ke ASR). Mic mentah tetap disimpan apa adanya, sehingga bila AEC gagal, rekaman asli tidak rusak.
- **Bila spike S3 gagal mencapai target:** pakai D di MVP (deteksi gema lewat korelasi silang, peringatan "gunakan headset", dan dedup segmen mic yang mirip segmen system pada waktu bersamaan). A dilanjutkan di Beta.
- **Sinkronisasi:**
  - Setiap blok audio diberi timestamp host (QPC di Windows, `mHostTime` di macOS).
  - Rasio drift diestimasi secara berkala, lalu dikoreksi dengan resampler asinkron (`rubato` v5.0.1, MIT, dicek 2026-10-08) di jalur yang membutuhkan keselarasan (AEC, mixing untuk playback/ekspor).
  - File mentah tidak diubah; metadata timeline disimpan.

---

## ADR-009: Runtime STT

| Kriteria (bobot) | A. whisper.cpp (whisper-rs 0.16) | B. transcribe.cpp (runtime ggml multi-model) | C. sherpa-onnx (ONNX Runtime) | D. faster-whisper (Python) |
|---|---|---|---|---|
| Kematangan (3) | `++` v1.9.5, 54k bintang | `0` baru (2026), sekitar 2k bintang, tidak ada rilis bertag | `+` v1.13.8 | `++` |
| Model Indonesia terbaik yang didukung (3) | `+` Whisper | `++` Whisper + **Qwen3-ASR** | `+` Whisper, Qwen3-ASR (terdaftar) | `+` Whisper |
| GPU Metal/Vulkan/CUDA (2) | `++` | `++` | `0` terutama CUDA | `-` CUDA saja |
| Tanpa Python, mudah di-bundle (3) | `++` | `++` | `+` (DLL ONNX Runtime) | `--` |
| Binding Rust (2) | `++` whisper-rs (Unlicense, kini di Codeberg) | `0` binding Rust tersedia (**perlu diverifikasi** kematangannya; Handy memakainya) | `++` crate `sherpa-onnx` resmi 1.13.8 | `--` |

**Keputusan:**
- Buat trait `AsrEngine` (input: PCM 16 kHz mono + opsi; output: segmen bertimestamp, opsional dengan kata). Pola ini diadaptasi dari `TranscriptionProvider` meetily, tetapi tanpa jejak migrasi yang setengah jadi.
- **MVP:** A (whisper.cpp) sebagai engine default karena paling matang.
- **Bila lulus S4:** B (transcribe.cpp) ditambahkan sebagai engine untuk Qwen3-ASR, dan menjadi default final pass bila menang di korpus Indonesia.
- C dipakai untuk diarization dan embedding speaker (ADR-012), bukan untuk ASR utama.
- **Build:**
  - Varian CPU portabel (`GGML_NATIVE OFF`, dispatch CPU runtime) + Vulkan untuk Windows, Metal untuk macOS.
  - Proses utama memilih binary `recap-asr` yang sesuai setelah probe GPU.
  - Bila varian GPU gagal dimuat, fallback ke CPU (pelajaran meetily #685).

---

## ADR-010: Model STT default per tier perangkat

Angka kecepatan berasal dari satu sumber (benchmark Handy, Ryzen 4750U, dicek 2026-10-08), dan WER Indonesia dari satu uji FLEURS pihak ketiga. **Semua harus divalidasi di spike S4** pada perangkat target dan korpus meeting Indonesia.

| Tier | Ciri | Draf live | Final pass | Catatan |
|---|---|---|---|---|
| **Hemat** | RAM 8 GB, tanpa GPU | Qwen3-ASR-0.6B (sekitar 4,3x real time di CPU), atau Whisper small q5; boleh dimatikan | Qwen3-ASR-0.6B atau 1.7B (sekitar 2x real time di CPU) | Whisper large-v3-turbo di CPU sekitar 0,8x real time, sehingga final pass 3 jam butuh hampir 4 jam. **Tidak layak** di tier ini |
| **Standar** | RAM 16 GB, iGPU (Vulkan/Metal) | Whisper small/medium q5 di GPU, atau Qwen3-ASR-0.6B | Qwen3-ASR-1.7B atau Whisper large-v3-turbo q5/q8 di GPU (sekitar 3,4x real time di iGPU) | |
| **Kuat** | Apple Silicon 16 GB+ atau GPU diskrit | Whisper large-v3-turbo atau Qwen3-ASR-1.7B | Whisper large-v3 / Qwen3-ASR-1.7B | |

**Keputusan:** Tier ditentukan otomatis lewat probe hardware saat onboarding, dan bisa diubah pengguna. Model diunduh saat dibutuhkan dengan pin SHA-256. Tabel di atas adalah **hipotesis**; pilihan final mengikuti hasil spike S4.

**Konsekuensi:**
- Qwen3-ForcedAligner tidak mendukung Indonesia, jadi timestamp per kata untuk Qwen3-ASR mungkin tidak tersedia (**perlu diverifikasi** di transcribe.cpp). Untuk MVP cukup timestamp tingkat segmen VAD.
- Diarization presisi (Beta) mungkin butuh timestamp kata. Opsinya:
  - memakai Whisper untuk segmen yang berisi pergantian speaker
  - memotong segmen di batas giliran diarization lalu mentranskripsi ulang

---

## ADR-011: VAD

| Kriteria | Silero VAD v6.2.3 | TEN VAD | WebRTC VAD | VAD bawaan whisper.cpp |
|---|---|---|---|---|
| Lisensi | MIT | Apache-2.0 + **klausul non-compete** | BSD-3 | MIT (model Silero) |
| Akurasi | `++` | `++` (klaim vendor) | `-` banyak false positive | `++` |
| Bisa streaming per kanal di luar STT | `++` | `++` | `++` | `-` terikat panggilan transkripsi |
| Dependensi | ONNX Runtime | lib sendiri | sangat kecil | sudah ada |

**Keputusan:**
- **Jalur live:** Silero VAD v6 lewat `ort` (ONNX Runtime) di dalam `recap-asr`, satu instance per kanal, frame 32 ms pada 16 kHz.
- **Final pass:** VAD bawaan whisper.cpp boleh dipakai untuk engine Whisper.
- **Runtime ONNX:** satu versi yang di-pin dan dibundel, dimuat dari folder aplikasi (`load-dynamic`), untuk menghindari DLL clash (amical #44).

---

## ADR-012: Diarization

| Opsi | Lisensi | Runtime | Catatan |
|---|---|---|---|
| A. Berbasis kanal (mic = Saya, system = Peserta) | n/a | gratis | Robust; tidak memisahkan peserta online satu sama lain atau peserta tatap muka |
| B. sherpa-onnx offline: segmentasi pyannote 3.0 + embedding 3D-Speaker/WeSpeaker + clustering | Apache-2.0 / MIT | ONNX, CPU | Tanpa Python. Kecepatan CPU belum ada data, harus di-benchmark |
| C. pyannote community-1 | CC-BY-4.0, gated | Python/PyTorch | Kualitas lebih baik, tetapi butuh Python |
| D. NVIDIA Streaming Sortformer / Nemotron-3-Diarization | CC-BY-4.0 / OpenMDW (**perlu diverifikasi**) | NeMo-Speech.cpp, GPU NVIDIA | Maksimal 4/8 speaker |
| E. Cloud (Deepgram, AssemblyAI, pyannoteAI) | berbayar | BYOK | Opsional |

**Keputusan:**
- **MVP:** A.
- **Beta:** B sebagai post-processing **offline** setelah meeting. Dijalankan pada kanal system (meeting online) atau kanal mic (meeting tatap muka), menghasilkan label anonim "Pembicara 1..N". Pengguna bisa mengganti nama dan menggabungkan speaker.
- **Diarization real-time tidak dikejar.** Label live cukup Saya/Peserta.
- **Tidak menyimpan voiceprint persisten** secara default (alasan privasi dan UU PDP, lihat dokumen 06).
- E tersedia sebagai opsi BYOK. C dan D tidak dibundel.

---

## ADR-013: Runtime LLM

| Kriteria (bobot) | A. llama.cpp tertanam via `llama-cpp-2` di sidecar | B. Wajib Ollama | C. Bundel `llama-server` (OpenAI-compatible) | D. Cloud saja |
|---|---|---|---|---|
| Out-of-the-box tanpa instal lain (3) | `++` | `--` | `++` | `--` |
| JSON valid terjamin (grammar dari JSON schema) (3) | `++` | `+` `format` schema | `++` `response_format` | `+` |
| Kontrol memori dan lifecycle (2) | `++` | `0` | `+` | n/a |
| Biaya integrasi (2) | `0` | `++` | `+` | `++` |
| Privasi (3) | `++` | `++` | `++` | `--` |

Versi dicek 2026-10-08: llama.cpp **v0.6.0** (2026-10-05), `llama-cpp-2` **0.1.159** (Apache-2.0), Ollama **v0.40.1**.

**Keputusan:**
- A sebagai default, di sidecar `recap-llm` (pola `llama-helper` meetily, tetapi model tetap termuat selama job lalu di-unload).
- Recap juga bisa memakai **provider eksternal**:
  - Ollama, LM Studio, atau server OpenAI-compatible apa pun (lokal)
  - cloud BYOK (ADR-022)
- Satu antarmuka `LlmProvider` dengan kemampuan `json_schema` (dukungan native atau fallback), mengadopsi tangga fallback prismical: native structured output, lalu tool call, lalu JSON lenient + perbaikan, lalu gagal dengan pesan jelas.

---

## ADR-014: Model LLM default

Data skor dari leaderboard SEA-HELM tanggal 2026-09-18. Angkanya diparsing dari data halaman sehingga **perlu diverifikasi**, dan SEA-HELM mengukur tugas umum, bukan ringkasan meeting.

| Tier | Model default | Skor ID | Ukuran Q4 | Lisensi | Alternatif |
|---|---|---|---|---|---|
| Hemat (8 GB) | **Qwen3.5-4B** Q4_K_M | 69,7 | sekitar 3,3 sampai 4 GB | Apache-2.0 | Gemma 4 E2B (64,1) |
| Standar/Kuat (16 GB+) | **Qwen3.5-9B** Q4_K_M | 74,2 | sekitar 6,6 sampai 7,6 GB | Apache-2.0 | **Gemma 4 12B** (74,5, sekitar 8 GB) |

**Keputusan:**
- Mode thinking dimatikan untuk ringkasan, atau memakai effort rendah.
- Jendela konteks kerja 8k sampai 16k token dengan map-reduce (dokumen 05), bukan 256K yang diklaim, karena memori KV cache di laptop terbatas.
- Model final dipilih lewat spike S6 dengan transkrip meeting Indonesia nyata.
- Gemma 3 dihindari sebagai default (Gemma Terms). Gemma 4 sudah Apache-2.0.

---

## ADR-015: Database dan pencarian

| Kriteria | A. SQLite WAL (rusqlite) + FTS5 + sqlite-vec | B. SQLite (sqlx async) | C. SQLite + LanceDB/Qdrant embedded | D. DuckDB |
|---|---|---|---|---|
| Kesederhanaan dan satu file | `++` | `++` | `0` dua store | `+` |
| Full-text Indonesia | `++` FTS5 `unicode61 remove_diacritics 2` (tanpa porter) | `++` | `+` | `0` |
| Vektor | `+` sqlite-vec v0.1.9 (Apache-2.0; pra-1.0, update terakhir 2026-05) | `+` | `++` | `0` |
| Kematangan crate | `++` rusqlite 0.40.2 (MIT) | `++` | `0` | `+` |

**Keputusan:**
- A dengan satu database `recap.db`. Mode WAL, `synchronous=NORMAL`, dan akses tulis tunggal lewat satu thread penulis di proses utama.
- sqlx tidak dipakai, untuk menghindari kerumitan async dan agar extension mudah dimuat.
- **Tidak pernah menghapus file WAL.** Bila DB rusak, salin ke `recap.db.corrupt-<ts>`, coba `.recover`, lalu beri tahu pengguna.
- **Pencarian:**
  - **MVP:** FTS5 atas segmen transkrip, judul, dan ringkasan.
  - **Beta:** hybrid BM25 + vektor (sqlite-vec) dengan reciprocal rank fusion.
- **Risiko:** sqlite-vec masih pra-1.0. Mitigasinya, simpan vektor juga sebagai BLOB di tabel biasa agar bisa di-reindex atau berpindah library.

---

## ADR-016: Model embedding

| Model | Ukuran | Lisensi | Catatan |
|---|---|---|---|
| **Qwen3-Embedding-0.6B** (GGUF) | 596M | Apache-2.0 | Konteks 32K, multilingual, bisa jalan di runtime llama.cpp yang sama |
| multilingual-e5-small | 118M | MIT | Sangat ringan untuk tier hemat |
| bge-m3 | 568M | MIT | Dense + sparse |
| EmbeddingGemma-300m | 303M | Gemma Terms, gated | Dihindari |

**Keputusan:**
- Tier standar/kuat: Qwen3-Embedding-0.6B (Q8).
- Tier hemat: multilingual-e5-small.
- Setiap vektor disimpan bersama `model_id` dan `dim` agar re-indexing aman.
- Indexing berjalan di background setelah meeting selesai, dengan prioritas rendah.

---

## ADR-017: Downloader URL

| Opsi | Catatan |
|---|---|
| A. yt-dlp sidecar, diunduh on-demand dan di-update otomatis (pola Vibe) | Unlicense. Butuh Deno untuk YouTube (EJS) dan kadang PO token. Sekitar 10 rilis per 8 bulan |
| B. yt-dlp dibundel dan di-pin | Rusak setiap kali YouTube berubah; harus rilis aplikasi (masalah Buzz) |
| C. cobalt | AGPL, berbasis server, bukan local-first |
| D. Hanya file lokal (pengguna mengunduh sendiri) | Paling aman secara hukum |

**Keputusan:**
- **D di MVP.**
- **A di Beta**, sebagai fitur **eksperimental** yang harus diaktifkan pengguna:
  - yt-dlp dan Deno baru diunduh saat fitur dipakai pertama kali, dengan verifikasi checksum dari rilis resmi.
  - Update dicek tiap kali dipakai, maksimal sekali per hari.
  - Hanya audio yang diunduh (`bestaudio`).
  - Tidak pernah mengambil cookies browser secara otomatis.
  - Disclaimer ToS dan hak cipta wajib disetujui sekali (dokumen 06).
  - Bila subtitle manual tersedia, pengguna bisa memilih memakai subtitle dan melewati STT.

---

## ADR-018: Decoder file import

| Opsi | Catatan |
|---|---|
| A. ffmpeg build LGPL sebagai sidecar | Semua container dan codec umum, termasuk Opus (WhatsApp) dan mkv/webm |
| B. symphonia (Rust) | Ringan, tetapi tidak semua codec (meetily #739: Opus gagal) |
| C. Decoder OS (Media Foundation / AVFoundation) | Beda per OS |

**Keputusan:**
- A untuk semua import. Format yang tidak dikenal juga dialihkan ke ffmpeg.
- ffmpeg juga dipakai untuk encode arsip Opus (ADR-007).
- Binary diambil dari sumber build LGPL yang tepercaya, di-pin dengan SHA-256 di CI. Source dan configure line dipublikasikan di halaman rilis sesuai syarat LGPL.
- B boleh dipakai untuk WAV/FLAC/MP3 sederhana bila mempercepat. Opsional.

---

## ADR-019: Stack UI

**Keputusan:**
- **Fondasi:** React 19 + TypeScript + Vite + Tailwind + komponen shadcn/ui (Radix, aksesibel).
- **Routing dan data:** TanStack Router + TanStack Query, dengan Tauri command sebagai sumber data.
- **i18n:** i18next dengan katalog **id** dan **en** sejak hari pertama.
- **Transkrip panjang:** list virtual (`@tanstack/react-virtual`).
- **Editor:** satu saja, Tiptap, untuk catatan dan ringkasan, mulai Beta. Di MVP, ringkasan ditampilkan dari JSON dengan edit per field.
- Next.js **tidak** dipakai (meetily memakai static export yang tidak perlu).

**Alasan:** Stack yang paling umum dan banyak contohnya, sehingga cocok untuk solo dev yang dibantu AI. Lalu ada satu editor, bukan tiga seperti meetily.

---

## ADR-020: Distribusi, signing, dan update

| Area | Keputusan |
|---|---|
| Installer Windows | NSIS (per-user, bisa pilih folder). MSIX/Microsoft Store dan winget menyusul di rilis publik |
| Installer macOS | DMG, arm64. Intel tidak didukung resmi |
| Linux (pasca-MVP) | AppImage + deb, lalu Flatpak |
| Signing macOS | Apple Developer Program (USD 99/tahun), Developer ID + Hardened Runtime + notarization. Entitlement `com.apple.security.device.audio-input`; `NSMicrophoneUsageDescription` dan `NSAudioCaptureUsageDescription` di Info.plist (ditulis manual) |
| Signing Windows | **SignPath Foundation** (gratis untuk OSS; daftar setelah repo publik dan punya rilis). Cadangan: sertifikat OV dengan cloud HSM (sekitar USD 150 sampai 300/tahun). Azure Artifact Signing **tidak tersedia** untuk Indonesia (dicek 2026-10-08) |
| Update aplikasi | `tauri-plugin-updater` + `latest.json` di GitHub Releases, ditandatangani minisign. Kanal stable dan beta |
| Update model | Katalog model (JSON bertanda tangan) terpisah dari rilis aplikasi. Unduhan bisa dilanjutkan, dengan SHA-256 |
| Telemetri | Tidak ada secara default. Crash report lokal yang bisa dilampirkan manual oleh pengguna |

**Risiko yang dicatat:**
- Ada laporan pendaftar Apple Developer dari Indonesia dengan nama tunggal (mononim) yang gagal enroll. Siapkan identitas yang konsisten.
- SmartScreen tetap memperingatkan di awal sampai reputasi terbentuk.

---

## ADR-021: Lisensi proyek

| Opsi | Catatan |
|---|---|
| MIT | Sederhana, kompatibel dengan semua referensi |
| Apache-2.0 | Ada patent grant dan klausul NOTICE |
| **MIT OR Apache-2.0** (dual) | Konvensi ekosistem Rust; pengguna bebas memilih |
| GPL-3.0 | Membuka akses ke kode GPL (noScribe), tetapi membatasi adopsi |

**Keputusan:**
- **MIT OR Apache-2.0.**
- File `THIRD_PARTY_NOTICES` dibuat otomatis (misalnya dengan `cargo-about` + `license-checker`).
- Atribusi model ditampilkan di layar Tentang.
- Kontribusi memakai DCO (sign-off), bukan CLA, agar ringan.

---

## ADR-022: Rahasia dan provider cloud (BYOK)

**Keputusan:**
- **Penyimpanan key:**
  - API key disimpan di keychain OS lewat crate `keyring` (v4.2.0, Apache-2.0): Windows Credential Manager, macOS Keychain, dan Secret Service di Linux.
  - Key **tidak pernah** masuk DB, log, atau ekspor.
- **Adapter LLM:**
  1. OpenAI-compatible: mencakup OpenAI, OpenRouter, Groq, Ollama, LM Studio, dan llama-server.
  2. Anthropic native.
  3. Gemini native.
- **Adapter STT:**
  1. Deepgram Nova-3 (`id`, diarization, streaming).
  2. OpenAI `gpt-4o-transcribe` / `-diarize`.
  3. OpenAI-compatible `/audio/transcriptions` (Groq, server whisper sendiri).
- **Semua cloud mati secara default.** Setiap kali data akan dikirim, UI menampilkan ringkasan: provider, data apa (audio atau teks), dan perkiraan ukuran. Pengguna bisa menyetujui per meeting atau "selalu untuk provider ini".
- Harga di UI tidak di-hardcode; cukup tautan ke halaman harga provider. Harga dicek ulang saat implementasi karena cepat berubah.

---

## ADR-023: Ekspor dokumen

**Keputusan:**
- **MVP:** Markdown (ringkasan + transkrip), TXT, SRT, dan VTT dari segmen bertimestamp. Ditambah salin ke clipboard.
- **Beta:**
  - **DOCX** via crate `docx-rs` (0.4.21, MIT).
  - **PDF** via **Typst** sebagai library (v0.15.1, Apache-2.0), dengan template ringkasan yang rapi. Alternatif yang lebih ringan: render HTML lalu cetak lewat WebView, dengan risiko konsistensi lintas OS.
- **Ekspor audio:** Opus/WAV per kanal atau campuran (dimix saat ekspor, dengan koreksi drift).

---

## Ringkasan dampak ke dokumen lain

- Arsitektur proses dan IPC (ADR-003) dijabarkan di dokumen 03.
- Pipeline AI (ADR-009 sampai 016) dijabarkan di dokumen 05.
- Skema data dan kebijakan rahasia (ADR-007, 015, 022) dijabarkan di dokumen 06.
- Semua ADR berstatus "Diusulkan" bergantung pada spike di dokumen 10:

| ADR | Spike |
|---|---|
| 004 | S1 |
| 005 | S2 |
| 008 | S3 |
| 009/010 | S4, S5 |
| 012 | S7 |
| 013/014 | S6 |
| 001/020 | S8 |
