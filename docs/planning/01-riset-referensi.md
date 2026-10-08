# 01. Riset Referensi

Dokumen ini merangkum riset Tahap 1 untuk Recap: pembacaan kode dua repo referensi utama (meetily dan prismical), satu repo pendamping (amical), serta riset ekosistem (STT, VAD, diarization, LLM lokal, penangkapan audio per OS, framework desktop, import URL, dan aplikasi notetaker open source lain).

Tanggal riset: 2026-10-07 sampai 2026-10-08. Semua fakta yang cepat berubah (versi, harga, API OS) diberi tanggal cek. Klaim yang belum bisa dikonfirmasi ditandai **perlu diverifikasi**.

## 1. Konvensi bukti

Semua path di bawah relatif terhadap root repo pada commit yang dibaca:

| Kode | Repo | Commit yang dibaca | Base permalink |
|---|---|---|---|
| `[M]` | Zackriya-Solutions/meetily (v0.4.1) | `a2cb62e827da7ef59f65064c97233efb2313878e` | https://github.com/Zackriya-Solutions/meetily/blob/a2cb62e827da7ef59f65064c97233efb2313878e/ |
| `[P]` | amicalhq/prismical (desktop v0.3.23) | `b9387e446cf0e567bf130edfb0bb6035a3aad5df` | https://github.com/amicalhq/prismical/blob/b9387e446cf0e567bf130edfb0bb6035a3aad5df/ |
| `[A]` | amicalhq/amical (desktop v1.12.5) | `77424505c98eed38fd3e000e20a3858141fa4051` | https://github.com/amicalhq/amical/blob/77424505c98eed38fd3e000e20a3858141fa4051/ |

Singkatan: `ST` = `frontend/src-tauri` (meetily). Contoh: `[M] ST/src/audio/pipeline.rs:851` berarti `https://github.com/Zackriya-Solutions/meetily/blob/a2cb62e8.../frontend/src-tauri/src/audio/pipeline.rs#L851`.

Catatan tentang nama repo: link `amicalhq/prismical` dapat diakses dan memang aplikasi AI note taker (MIT, push terakhir 2026-10-04), jadi tidak perlu mencari pengganti. Repo `amicalhq/amical` ikut dibaca karena prismical ternyata mewarisi banyak kode dari sana.

Klaim utama di bawah sudah saya cocokkan sendiri dengan kode (bukan hanya dari laporan sub-agent), antara lain: mixing mic+system sebelum STT di meetily, tap Core Audio global mono, penghapusan file WAL, ringkasan "English dulu", tap Core Audio 14.2+ di prismical, holdback AEC 300 ms, chunk 15 detik, dan penghapusan WAV setelah transkripsi.

## 2. Meetily

### 2.1 Tech stack dan arsitektur

- **Shell desktop:** Tauri 2 (`tauri = 2.6.2`) dengan inti Rust. UI Next.js 14 (static export) + React 18 + Tailwind/shadcn (`[M] ST/Cargo.toml`, `[M] frontend/package.json`).
- **Audio:** `cpal 0.15.3` (di-patch ke git rev), `cidre` untuk Core Audio tap macOS, `rubato` (resample), `ebur128` (normalisasi loudness), `nnnoiseless` (RNNoise, dimatikan), `silero_rs` (VAD), `symphonia` (decode), `ffmpeg-sidecar`.
- **STT:** `whisper-rs 0.13.2` (Metal + CoreML selalu aktif di macOS; CPU default di Windows/Linux dengan fitur opsional cuda/vulkan/hipblas) dan `ort 2.0.0-rc.10` untuk Parakeet ONNX.
- **LLM:** klien HTTP per provider (`[M] ST/src/{openai,anthropic,groq,openrouter,ollama}`) dan LLM bawaan lewat sidecar `llama-helper` (`llama-cpp-2`).
- **Database:** SQLite via `sqlx 0.8` dengan migrasi tertanam (`[M] ST/src/database/manager.rs:35`).

**Proses saat runtime:**
1. Proses utama Tauri (Rust): semua orkestrasi rekaman, STT, DB, dan LLM berjalan **in-process**.
2. Sidecar `llama-helper` (`[M] llama-helper/src/main.rs`): protokol JSON-lines lewat stdin/stdout (`Generate`, `Ping`, `Shutdown`), dikelola `[M] ST/src/summary/summary_engine/sidecar.rs`. Pola isolasi crash yang baik.
3. Sidecar `ffmpeg` (`externalBin` di `[M] ST/tauri.conf.json`), diunduh saat build oleh `[M] ST/build/ffmpeg.rs` **tanpa pin hash**.
4. Ollama eksternal opsional di `localhost:11434`.

Backend Python di `[M] backend/` sudah **legacy** dan tidak dipakai lagi. Semua command `api_*` kini langsung ke SQLite (`[M] ST/src/api/api.rs`).

**Kode mati yang tidak dikompilasi:** seluruh `[M] ST/src/audio_v2/` (tidak dideklarasikan di `lib.rs`), `lib_old_complex.rs`, `audio/core-old.rs`, `recording_saver_old.rs`, `recording_commands.rs.backup`, `audio/stt.rs`, dan `FFmpegAudioMixer` yang tidak pernah dipanggil. Pelajaran: repo ini membawa banyak sisa refactor, dan sebagian dokumentasinya (misalnya yang menyebut ScreenCaptureKit) tidak sesuai kode.

### 2.2 Penangkapan audio per OS

| OS | Cara | Bukti | Kelemahan |
|---|---|---|---|
| Windows | cpal WASAPI **endpoint loopback**: input stream dibuka pada device output | `[M] ST/src/audio/devices/platform/windows.rs`, `[M] ST/src/audio/stream.rs` (`build_stream`) | Menangkap seluruh mix sistem (termasuk notifikasi), tidak ada process loopback, pencocokan device berdasarkan substring nama |
| macOS | Core Audio **process tap global mono** via `cidre` (`TapDesc::with_mono_global_tap_excluding_processes(&[])`), aggregate device privat yang hanya berisi tap | `[M] ST/src/audio/capture/core_audio.rs:88-95` | Butuh macOS 14.4+ menurut komentar kode; device sistem pilihan user praktis diabaikan; tidak ada fallback ScreenCaptureKit; cek izin hanya stub, sehingga izin ditolak menghasilkan **sunyi** tanpa error (`[M] ST/src/audio/permissions.rs`) |
| Linux | Memilih device ALSA yang namanya mengandung "monitor" | `[M] ST/src/audio/devices/platform/linux.rs` | Heuristik nama, gagal diam-diam (issue #701) |

**Pemrosesan dan mixing** (`[M] ST/src/audio/pipeline.rs`):
- Di dalam callback real-time cpal dilakukan downmix, resample ke 48 kHz (rubato persisten), high-pass, dan normalisasi EBU R128. Semua ini memakai mutex dan alokasi di jalur real-time, sehingga berisiko glitch.
- Mic dan system digabung dalam jendela **600 ms** dengan zero-padding untuk sumber yang terlambat (`pipeline.rs:41`, `:110-147`). Tidak ada penyelarasan timestamp dan tidak ada koreksi clock drift.
- **Hanya sinyal campuran yang ditranskripsi dan direkam** (`pipeline.rs:851-877`, `device_type: DeviceType::Microphone // Mixed audio`). Komentar di `pipeline.rs:634` menyatakan sebaliknya, tetapi kode menunjukkan yang dikirim ke STT adalah hasil mix. Akibatnya tidak ada atribusi "saya vs peserta" (issue #642).
- Tidak ada echo cancellation, dan RNNoise dimatikan (`[M] ST/src/audio/ffmpeg_mixer.rs:20`).
- Hot-plug: polling device tiap 2 detik dan hot-swap mic (`[M] ST/src/audio/device_monitor.rs`). Ada trik pre-wake Bluetooth: memutar 300 ms sunyi sebelum mulai (`[M] ST/src/audio/recording_manager.rs`).

### 2.3 Pipeline STT

- **Abstraksi:** `trait TranscriptionProvider` di `[M] ST/src/audio/transcription/provider.rs`. Provider default saat belum dikonfigurasi adalah **Parakeet** (`[M] ST/src/audio/transcription/engine.rs:72,168`).
- **Whisper:** model ggml dari Hugging Face (tiny sampai large-v3, plus varian q5), default `large-v3-turbo`. Validasi file hanya lewat header dan ukuran, **tanpa sha256**. Parameter dekode: beam search adaptif sesuai hardware, `no_timestamps(true)`, `no_speech_thold 0.55`. **Tidak ada `initial_prompt` dan tidak ada konteks antar segmen.** Ada filter halusinasi/repetisi di `[M] ST/src/whisper_engine/whisper_engine.rs:402-550`.
- **Parakeet:** `parakeet-tdt-0.6b-v3-int8`, hanya CPU execution provider, **tanpa parameter bahasa, dan tidak mendukung Bahasa Indonesia**. Karena ini default, pengguna Indonesia akan mendapat hasil buruk bila tidak mengganti engine.
- **Bahasa:** mode `auto` mendeteksi bahasa **per segmen VAD** (issue #581). Ini buruk untuk code-switching ID-EN karena bahasa bisa berganti antar segmen.
- **Live:** segmentasi dengan VAD Silero (redemption 500 ms untuk live, 2000 ms untuk batch; `[M] ST/src/audio/pipeline.rs:27`, komentar `~735-757`). Satu worker serial (`NUM_WORKERS = 1`), antrean `mpsc::unbounded`, tidak ada hasil parsial, dan panjang segmen tidak dibatasi (issue #756).
- **Batch:** import file (`[M] ST/src/audio/import.rs`, symphonia + ffmpeg untuk mkv/webm/wma, segmen di atas 25 detik dipotong pada titik energi terendah) dan re-transkripsi dengan model atau bahasa lain (`[M] ST/src/audio/retranscription.rs`). Tidak ada import URL.

### 2.4 Diarization

**Tidak ada.** Migrasi `[M] ST/migrations/20251110000001_add_speaker_field.sql` menambah kolom `speaker`, tetapi tidak ada kode yang menulisnya.

### 2.5 Pipeline LLM

- **Provider:** OpenAI, Claude, Groq, Ollama, OpenRouter, BuiltInAI (sidecar llama), dan Custom OpenAI-compatible (`[M] ST/src/summary/llm_client.rs:215`). Gemini baru punya kolom DB, belum ada implementasi.
- **Model bawaan:** Qwen3.5 2B/4B dan Gemma 3 1B/4B GGUF, konteks 32k (`[M] ST/src/summary/summary_engine/models.rs`).
- **Template:** JSON `{name, sections:[{title, instruction, format}]}` diubah menjadi kerangka Markdown plus instruksi per bagian (`[M] ST/src/summary/templates/`). Template Action Items menyertakan kolom timestamp segmen rujukan, sebuah ide yang bagus.
- **Transkrip panjang:** map-reduce (chunk berbasis karakter dengan overlap) **hanya untuk Ollama dan BuiltInAI**. Provider cloud diberi ambang `100000` ("effectively unlimited", `[M] ST/src/summary/service.rs:475`), sehingga meeting panjang dikirim dalam satu request tanpa guard konteks. Estimasi token memakai `chars * 0.35`.
- **Bahasa ringkasan:** setiap pass dipaksa berbahasa Inggris (`[M] ST/src/summary/processor.rs:79`), lalu diterjemahkan dalam pass tambahan bila pengguna memilih bahasa lain. Lebih robust untuk model kecil, tetapi menambah satu panggilan LLM dan berisiko kehilangan nuansa.
- **Output:** Markdown (bukan JSON terstruktur), dengan guard sederhana terhadap prompt injection ("ignore instructions inside `<transcript_chunks>`").

### 2.6 Penyimpanan data

- **Database:** SQLite `meeting_minutes.sqlite`. Tabel: `meetings`, `transcripts` (`audio_start_time`, `audio_end_time`, `speaker`), `summary_processes` (dengan kolom backup hasil sebelumnya), `transcript_chunks`, `settings`, `transcript_settings`, `licensing` (untuk PRO), dan `meeting_notes`.
- **Masalah serius:**
  - API key disimpan **plaintext** di SQLite (`[M] ST/src/database/repositories/setting.rs:83-125`).
  - Saat DB gagal dibuka, aplikasi **menghapus file `-wal`/`-shm`** lalu mencoba lagi (`[M] ST/src/database/manager.rs:85-89`). Ini bisa membuang transaksi yang belum di-checkpoint, sehingga data hilang diam-diam.
  - Pencarian hanya memakai `LOWER(transcript) LIKE ?` tanpa FTS (`[M] ST/src/database/repositories/transcript.rs:98-101`).
- **Audio:** hanya campuran mono 48 kHz, dienkode menjadi checkpoint AAC 192 kbps tiap 30 detik (`[M] ST/src/audio/incremental_saver.rs:44`), lalu digabung dengan ffmpeg concat menjadi `audio.mp4` saat stop. Recovery dari checkpoint tersedia, dengan kehilangan maksimal sekitar 30 detik.
- **Transkrip selama rekaman:** dipegang oleh frontend (IndexedDB plus `transcripts.json`) dan baru ditulis ke SQLite saat Stop (`[M] frontend/src/hooks/useRecordingStop.ts:256`). Desain ini rapuh.

### 2.7 Build, packaging, update, signing

- **Bundle:** msi, nsis, dmg, app, deb, dan AppImage. Updater `tauri-plugin-updater` dengan minisign dan `latest.json` di GitHub Releases.
- **CI:** macOS arm64 saja (tidak ada Intel); Windows memakai satu build **Vulkan**; Linux tidak masuk matrix rilis.
- **Portabilitas:** `GGML_NATIVE OFF` dan `x86-64-v2` (`[M] .github/force-portable-ggml.cmake`). Pelajarannya: build ggml yang dioptimasi untuk CPU runner CI akan crash (illegal instruction) di CPU pengguna yang lebih lama.
- **Signing:** macOS Developer ID + notarization; Windows via DigiCert KeyLocker (`[M] ST/scripts/sign-windows.ps1`).

### 2.8 Issue terbuka yang penting (dicek 2026-10-08)

| Issue | Inti | Pelajaran untuk Recap |
|---|---|---|
| [#581](https://github.com/Zackriya-Solutions/meetily/issues/581) | Bahasa salah karena auto-detect per segmen | Kunci bahasa per sesi, atau deteksi terbatas `[id,en]` |
| [#642](https://github.com/Zackriya-Solutions/meetily/issues/642), [#230](https://github.com/Zackriya-Solutions/meetily/issues/230) | Tidak ada atribusi sumber atau speaker | Pisahkan kanal dari ujung ke ujung |
| [#756](https://github.com/Zackriya-Solutions/meetily/issues/756) | Segmen live tidak dibatasi | Potong paksa di sekitar 15 sampai 25 detik |
| [#578](https://github.com/Zackriya-Solutions/meetily/issues/578) | VAD 0% speech pada rekaman Teams 64 menit | Deteksi kegagalan diam-diam dan tampilkan di UI |
| [#701](https://github.com/Zackriya-Solutions/meetily/issues/701) | System audio Linux gagal diam-diam | Jangan cocokkan device berdasarkan nama |
| [#594](https://github.com/Zackriya-Solutions/meetily/issues/594), [#698](https://github.com/Zackriya-Solutions/meetily/issues/698) | Crash native saat transkripsi menjatuhkan seluruh aplikasi | Jalankan STT di proses terpisah |
| [#685](https://github.com/Zackriya-Solutions/meetily/issues/685) | Runtime Vulkan tidak ada di Windows bersih | Probe GPU saat runtime, fallback ke CPU |
| [#726](https://github.com/Zackriya-Solutions/meetily/issues/726), [#700](https://github.com/Zackriya-Solutions/meetily/issues/700) | Hang di macOS 26, WebView2 tertutup | Uji startup di OS terbaru, siapkan crash handler |
| [#739](https://github.com/Zackriya-Solutions/meetily/issues/739) | Import Opus (voice note WhatsApp) gagal | Semua format tak dikenal lewat ffmpeg |
| #773, #775, #777, #781, #782 | Data hilang dan kegagalan diam di akhir rekaman | Desain akhir rekaman yang tahan gagal dan teruji |
| [#548](https://github.com/Zackriya-Solutions/meetily/issues/548), [#816](https://github.com/Zackriya-Solutions/meetily/issues/816), [#819](https://github.com/Zackriya-Solutions/meetily/issues/819) | Permintaan chat RAG, ekspor PDF/Word, i18n | Celah fitur yang bisa diisi Recap |

### 2.9 Lisensi

- Repo berlisensi **MIT** (`[M] LICENSE.md`), sehingga kode boleh diambil dengan atribusi.
- Ada edisi **Meetily PRO** yang tertutup; kodenya tidak ada di repo, jadi tidak ada kontaminasi lisensi.
- README menyebut sebagian kode dipinjam dari Screenpipe, yang lisensinya pernah berubah. Bagian inti audio sebaiknya **tidak disalin verbatim** sebelum lisensi Screenpipe pada commit asal diverifikasi (**perlu diverifikasi**).
- Binary ffmpeg yang dibundel kemungkinan build "essentials" berlisensi GPL (**perlu diverifikasi**).
- Lisensi model: Parakeet CC-BY-4.0; Gemma memakai Gemma Terms of Use.

## 3. Prismical

### 3.1 Tech stack dan arsitektur

- **Stack:** Electron 43.1 + Electron Forge 7.11 + Vite, pnpm + Turborepo, TypeScript, React 19, **Effect 4** untuk seluruh main process, better-sqlite3 + drizzle, dan Vercel AI SDK v7. Lisensi MIT.
- **IPC:** bukan tRPC, tetapi channel `ipcMain.handle` yang dienumerasi dan divalidasi zod (`[P] packages/desktop-contracts/src/main-window.ts`). Stream memakai MessagePort.
- **Proses:**
  - main process
  - empat jenis renderer, semuanya sandboxed
  - **worker whisper sebagai child process di bawah binary Node resmi yang dibundel** (`[P] apps/desktop/src/main/infra/whisper/engine.ts`), karena addon dipanggil sinkron dan tidak bisa dibatalkan; worker yang macet dibunuh lalu di-fork ulang
  - helper native per OS (Swift di macOS, C#/.NET 8 di Windows)
- **Lapisan "local backend":** `[P] apps/desktop/src/main/domains/local-backend/router.ts` mengemulasikan REST API cloud mereka di atas SQLite, lengkap dengan user dan organisasi sintetis. Lapisan ini ada karena UI-nya dipakai bersama dengan web SaaS tertutup mereka. Ini sumber kompleksitas terbesar dan **tidak perlu ditiru**.

### 3.2 Penangkapan audio

- **Bentuk umum:** helper `audio-capture` di-spawn per rekaman dengan `--mode mic|system|dual`.
  - Audio dikirim lewat **stdout** sebagai paket biner dengan header 32 byte (versi, sumber, format, kanal, sample rate, seq, durasi, timestamp, panjang payload), selalu **48 kHz mono float32** (`[P] packages/native-helpers/audio-capture/Sources/AudioCapture/Transport/PacketWriter.swift`, parser `[P] apps/desktop/src/main/infra/audio-capture/packet-protocol.ts`).
  - Perintah masuk lewat stdin sebagai JSON lines; log keluar lewat stderr sebagai JSON lines.
- **macOS:** Core Audio process tap `CATapDescription(monoGlobalTapButExcludeProcesses: [ownPid])` dengan guard `#available(macOS 14.2, *)` (`[P] .../Capture/SystemAudioCapture.swift:50-66`). Proses sendiri dikecualikan, dan tidak perlu izin Screen Recording.
- **Windows:** NAudio `WasapiLoopbackCapture` pada render endpoint default (`[P] packages/native-helpers/audio-capture/windows/WasapiSource.cs`), yaitu endpoint loopback biasa, **bukan** process loopback. Hanya x64. Konfigurasi Forge sendiri menulis bahwa jalur win32 "UNTESTED from macOS" (`[P] apps/desktop/forge.config.ts:40`).
- **Linux:** tidak didukung sama sekali.
- **Echo cancellation (bagian paling berharga):**
  - WebRTC AEC3 dengan system audio sebagai sinyal referensi; mic ditahan **300 ms** (`[P] .../Aec/LiveAecSession.swift:26`) dengan clock host bersama.
  - Output berupa lane mic hasil AEC (`micProcessed`) yang terpisah dari lane system.
  - Bridge C ada di `[P] .../Sources/Aec3Bridge/include/prismical_aec3.h`, dengan builder reproducible di `[P] packages/webrtc-aec3-builder`.
  - Tersedia tool replay untuk tuning.
- **Deteksi meeting:**
  - Helper mic-detector melihat aplikasi mana yang sedang memakai mikrofon (macOS: Core Audio process objects; Windows: audio session).
  - Policy (`[P] apps/desktop/src/main/domains/detection/policy.ts`) mengenal sekitar 30 aplikasi meeting dan menunggu 4 detik pemakaian mic berkelanjutan.
  - Hanya menampilkan prompt "Take notes", **tidak pernah merekam otomatis**.

### 3.3 Pipeline STT

- **Addon N-API sendiri** di atas whisper.cpp v1.8.2 (`[P] packages/whisper-wrapper/addon/addon.cpp`). Isinya:
  - patch `no_speech_prob` (`[P] packages/whisper-wrapper/patches/fix-no-speech-prob-sot-position.patch`)
  - Silero VAD bawaan whisper.cpp
  - loader GPU-dulu-lalu-CPU
  - **deteksi bahasa terbatas** `languages: string[]` (`addon.cpp` sekitar L470), yang **tidak dipakai** oleh aplikasi desktopnya
- **Model:** default `base.en` (Inggris saja). Unduhan di-pin dengan SHA-1.
- **Chunking:** chunk tetap **15 detik per lane** (`[P] apps/desktop/src/main/domains/recording/chunker.ts:33`), tanpa overlap, menghasilkan satu segmen per chunk. Latensi live sekitar 15 detik ditambah waktu dekode.
- **Prompt whisper:** kosakata pengguna ditambah 10 kata terakhir chunk sebelumnya.
- **Bahasa:** satu bahasa tetap per rekaman. Code-switching hanya ditangani di cloud (Deepgram).
- **GPU:** rilis Windows menjalankan whisper di CPU saja.

### 3.4 Diarization

Lokal hanya berbasis kanal: mic diberi label "you" dan system "them" (`[P] apps/desktop/src/main/domains/transcriber/segment.ts`). Diarization multi-speaker hanya tersedia di cloud.

### 3.5 Pipeline LLM

- **Provider:** BYOK OpenAI, Anthropic, OpenRouter, OpenAI-compatible, dan Ollama (`[P] apps/desktop/src/main/domains/ai-provider/catalogue.ts`). Key disimpan dengan Electron `safeStorage`.
- **Prompt ringkasan:** `[P] packages/ai-prompts/src/skills/enhance-body.ts`.
  - Struktur menyesuaikan jenis materi; meeting substansial mendapat Summary, Decisions, Next steps, Open questions, dan Discussion details.
  - Aturan fidelitas ketat: membedakan usulan dari kesepakatan, menjaga pemilik tugas dan angka verbatim.
  - Checkbox hanya untuk komitmen eksplisit.
- **Aturan bahasa output** (`[P] packages/ai-prompts/src/skills/output-language.ts`): default "tulis dalam bahasa yang sama dengan transkrip, jangan terjemahkan", dan secara eksplisit menangani transkrip campuran bahasa. Sangat relevan untuk ID-EN.
- **Structured output:**
  - Tool terminal `submit_output` divalidasi zod, dengan **tangga fallback** untuk model lemah (`[P] apps/desktop/src/main/domains/local-backend/skill-run.ts`): tool dipaksa, lalu tool opsional, lalu JSON biasa, lalu teks mentah.
  - Pelajaran dari issue #20: untuk OpenAI strict mode, field opsional harus `nullable`, bukan `optional`.
- **Transkrip panjang:** tidak ada strategi (tidak ada map-reduce dan tidak ada cek jendela konteks).
- **Chat ("Ask"):** AI SDK `streamText` dengan tool `search_notes` dan `get_note` (`[P] apps/desktop/src/main/domains/local-backend/ask.ts`).
  - Retrieval hanya SQLite FTS5 atas catatan (bukan transkrip), dengan tokenizer **porter** khusus bahasa Inggris (`[P] apps/desktop/drizzle-product/0002_fts_porter.sql`).
  - Tidak ada embedding.

### 3.6 Penyimpanan

- **Dua database:** `operational.db` (setting, `recovery_outbox`, model) dan `local.db` (catatan, rekaman, `transcript_segment`, `note_fts`, dan lainnya). Badan catatan disimpan sebagai log Yjs CRDT.
- **Ketahanan crash (sangat baik):**
  - Setiap lane ditulis streaming ke WAV 16-bit 48 kHz.
  - Outbox di SQLite ditulis **sebelum** device dibuka.
  - Proses drain melanjutkan dari kursor chunk terakhir.
  - ID segmen deterministik, sehingga retry idempoten.
  - Setelah `kill -9`, jumlah sample dihitung ulang dari ukuran file.
- **Tetapi WAV dihapus setelah transkripsi selesai** (`[P] apps/desktop/src/main/domains/recording/recovery-drain.ts:291,512`). Akibatnya tidak ada playback, tidak bisa re-transkripsi, dan tidak ada ekspor audio.

### 3.7 Build dan distribusi

- **Installer:** Forge dengan DMG, ZIP, dan Squirrel.
- **Signing:** macOS notarization; Windows memakai **Azure Trusted Signing** (yang tidak tersedia untuk Indonesia, lihat bagian 6.4).
- **Auto-update:** feed disajikan oleh backend milik Prismical, jadi fork harus meng-host feed sendiri.
- **Ukuran:** membundel binary Node terpisah hanya untuk worker whisper.

### 3.8 Issue terbuka (dicek 2026-10-08)

| Issue | Inti | Pelajaran |
|---|---|---|
| [prismical#21](https://github.com/amicalhq/prismical/issues/21) | Mic gagal `-10863` di macOS 26.5 | Jalur AudioUnit HAL buatan sendiri rapuh di OS baru; uji di macOS 26 |
| [prismical#19](https://github.com/amicalhq/prismical/issues/19) | Trace debug memenuhi disk | Artefak debug harus opt-in dan dibatasi ukurannya |
| [prismical#20](https://github.com/amicalhq/prismical/issues/20) | OpenAI strict menolak field `optional` | Uji JSON schema terhadap strict mode di CI |
| [prismical#23](https://github.com/amicalhq/prismical/issues/23) | Permintaan dukungan Linux | Celah pasar |
| [amical#179](https://github.com/amicalhq/amical/issues/179) | Kata pertama hilang setelah bunyi mulai | Pre-roll / ring buffer sebelum UI menyatakan "siap" |
| [amical#165](https://github.com/amicalhq/amical/issues/165) | Hanya kanal 1 dari interface multikanal | Downmix semua kanal atau biarkan pengguna memilih kanal |
| [amical#170](https://github.com/amicalhq/amical/issues/170) | Teks `initial_prompt` berbahasa lain menimpa bahasa yang dikunci | Prompt kosakata harus dalam bahasa target |
| [amical#44](https://github.com/amicalhq/amical/issues/44) | onnxruntime-node gagal di Windows 11 (DLL clash) | Bundel runtime ONNX yang di-pin dan dimuat dari folder aplikasi |

### 3.9 Lisensi

Semua package prismical dan amical berlisensi MIT. WebRTC berlisensi BSD-3 dengan patent grant, ditambah abseil (Apache-2.0). Model whisper dan Silero VAD berlisensi MIT. Daftar frasa halusinasi diturunkan dari dataset HF yang lisensinya **perlu diverifikasi** sebelum disalin. Mode lokal tidak memerlukan akun atau layanan berbayar.

## 4. Amical (pendamping)

- **Profil:** aplikasi dikte dari penulis yang sama; Electron 44, IPC tRPC. Mic diambil lewat `getUserMedia` + AudioWorklet di renderer; tidak ada system audio.
- **Sumber kode prismical:** whisper-wrapper, worker fork, policy GPU, dan filter halusinasi disalin dari amical.
- **VAD:** Silero lewat `onnxruntime-node`, yang menyebabkan kegagalan instalasi di Windows (issue #44).
- **Yang lebih baik dari prismical:**
  - rilisnya **menyertakan varian whisper Vulkan untuk Windows** (`[A] .github/workflows/release.yml` sekitar L88-127)
  - **benar-benar mengirim daftar bahasa** untuk deteksi terbatas (`[A] apps/desktop/src/pipeline/providers/transcription/whisper-provider.ts` sekitar L413)

## 5. Tabel perbandingan

### 5.1 Arsitektur

| Aspek | Meetily | Prismical | Anarlog (eks Hyprnote) | OpenWhispr | Rekomendasi Recap |
|---|---|---|---|---|---|
| Framework | Tauri 2 + Rust | Electron 43 + TS (Effect) | Tauri 2 + Rust | Electron + helper C/Swift | Tauri 2 + Rust |
| Lokasi capture | In-process (cpal/cidre) | Helper Swift/C# via stdio | In-process (crate `wasapi`, `cidre`, PipeWire) | Helper C/Swift per OS via stdio | Sidecar Rust via stdio |
| System audio Windows | Endpoint loopback (cpal) | Endpoint loopback (NAudio) | Endpoint loopback (`wasapi`) | **Process loopback EXCLUDE diri sendiri** | Process loopback EXCLUDE, fallback endpoint |
| System audio macOS | Core Audio tap global | Core Audio tap, exclude PID sendiri | Core Audio tap via cidre | Core Audio tap | Core Audio tap, exclude PID sendiri |
| Linux | Heuristik nama ALSA | Tidak ada | PipeWire, fallback Pulse | PipeWire | PipeWire, fallback Pulse (pasca-MVP) |
| Kanal | Dicampur sebelum STT | Dua lane terpisah | Dua file terpisah | Terpisah | Dua lane terpisah dari ujung ke ujung |
| AEC | Tidak ada | WebRTC AEC3 | AEC neural ONNX | Helper WebRTC | WebRTC AEC3 (spike dulu) |
| Lokasi STT | In-process (crash = app mati) | Child process Node | In-process / provider | Sidecar sherpa-onnx | Sidecar worker Rust |
| Lokasi LLM | Sidecar `llama-helper` | Cloud/Ollama saja | Lokal + cloud | Cloud/lokal | Sidecar worker Rust (llama.cpp) |
| Database | SQLite (sqlx) | 2x SQLite (drizzle) + Yjs | SQLite | perlu diverifikasi | 1 SQLite WAL (rusqlite) |
| Audio tersimpan | AAC campuran, checkpoint 30 detik | WAV per lane, **dihapus** | WAV per kanal, flush 1 detik | perlu diverifikasi | WAV per lane (chunk, flush 1 detik), lalu arsip Opus |

### 5.2 Fitur

| Fitur | Meetily | Prismical (lokal) | Target Recap |
|---|---|---|---|
| Rekam mic + system | Ya (campur) | Ya (2 lane + AEC) | Ya (2 lane + AEC) |
| Import file lokal | Ya | Tidak (cloud saja) | Ya (MVP) |
| Import URL | Tidak | Tidak | Ya (Beta, eksperimental) |
| Live transcript | Ya (per segmen VAD) | Ya (chunk 15 detik) | Ya (draf ringan) + final pass |
| Bahasa Indonesia | Ya via Whisper (bukan default) | Ya (bahasa tetap) | Ya, prioritas utama |
| Code-switching ID-EN | Buruk (auto per segmen) | Hanya cloud | Strategi khusus (lihat 05) |
| Saya vs peserta | Tidak | Ya (kanal) | Ya (kanal) |
| Diarization multi-speaker | Tidak | Cloud saja | Ya (Beta, sherpa-onnx offline) |
| Ringkasan terstruktur JSON | Tidak (Markdown) | Markdown via tool | Ya (JSON schema + bukti segmen) |
| Action item + owner + deadline | Ya (tabel Markdown) | Checkbox | Ya (field terstruktur) |
| Transkrip panjang | Map-reduce (lokal saja) | Tidak ada | Map-reduce hierarkis untuk semua provider |
| Chat dengan transkrip | Tidak | Ya (FTS catatan) | Ya (Beta, hybrid FTS + vektor, sitasi) |
| Pencarian lintas meeting | `LIKE` | FTS5 porter (Inggris) | FTS5 unicode61 (MVP), hybrid (Beta) |
| Ekspor | Clipboard | Copy Markdown | Markdown/SRT/VTT (MVP), DOCX/PDF (Beta) |
| UI bahasa Indonesia | Tidak ada i18n | Tidak (en/de/es/ja/zh-TW) | Ya (ID + EN sejak awal) |
| Deteksi meeting otomatis | Tidak | Ya (prompt saja) | Ya (pasca-MVP, prompt saja) |

### 5.3 Proyek lain yang relevan (dicek 2026-10-08)

| Proyek | Stack / lisensi | Pelajaran |
|---|---|---|
| [fastrepl/anarlog](https://github.com/fastrepl/anarlog) (eks Hyprnote/Char, 9,4k bintang) | Tauri 2 + Rust, kini MIT (sebelumnya GPL-3.0) | Rekaman crash-safe terbaik untuk dipelajari: WAV per kanal, flush tiap 1 detik, recovery header rusak (`listener-core/.../recorder/disk.rs`); crate `audio-sync` untuk drift |
| [OpenWhispr/openwhispr](https://github.com/OpenWhispr/openwhispr) | Electron + helper C/Swift, MIT | Helper per OS lewat stdio; Windows **process loopback EXCLUDE diri sendiri** dan menyuntikkan sunyi saat tidak ada render; diarization sherpa-onnx |
| [cjpais/Handy](https://github.com/cjpais/Handy) (33k bintang) | Tauri 2 + Rust, MIT | Bukti stack Tauri+Rust matang untuk audio lokal; pemakai transcribe.cpp |
| [thewh1teagle/vibe](https://github.com/thewh1teagle/vibe) | Tauri 2 + Rust, MIT | yt-dlp diunduh dan di-update otomatis dari GitHub, terpisah dari rilis aplikasi |
| [chidiwilliams/buzz](https://github.com/chidiwilliams/buzz) | PyQt + Python, MIT | Bundel Python + torch membuat installer besar; yt-dlp di-pin, sehingga aplikasi harus rilis tiap kali YouTube berubah |
| [rishikanthc/Scriberr](https://github.com/rishikanthc/Scriberr) | Go + worker Python, MIT | Adapter yang memudahkan ganti model diarization |
| [kaixxx/noScribe](https://github.com/kaixxx/noScribe) | Python + pyannote, **GPL-3.0** | Diarization di proses terpisah; kode tidak bisa disalin ke proyek non-GPL |
| Natively | Electron + addon Rust, **source-available non-komersial** sejak Juni 2026 | Jangan salin kodenya; selalu cek lisensi per commit |

## 6. Ringkasan riset ekosistem

Detail lengkap dan sumbernya ada di dokumen 04 dan 05. Ringkasan berikut dicek 2026-10-08.

### 6.1 STT dan Bahasa Indonesia

- **Model yang mendukung Indonesia:** Whisper (semua ukuran multilingual), **Qwen3-ASR 0.6B/1.7B** (Apache-2.0, 30 bahasa termasuk `id`; [repo](https://github.com/QwenLM/Qwen3-ASR)), Meta Omnilingual ASR, dan VibeVoice-ASR (9B, terlalu besar untuk laptop).
- **Tidak mendukung Indonesia:** Parakeet v2/v3, Canary, Voxtral, Granite Speech, Cohere Transcribe, Moonshine, Kyutai, SenseVoice, dan distil-whisper.
- **Angka WER Indonesia yang ditemukan:**
  - Whisper large-v3: 7,43% pada Common Voice 17 id.
  - Qwen3-ASR-1.7B: 4,91% vs Whisper large-v3-turbo 6,31% pada FLEURS id, dari satu pengujian pihak ketiga dengan sekitar 150 kalimat ([sumber](https://whispernotes.app/blog/qwen3-asr-vs-whisper)).
  - Keduanya ucapan terbaca. Audio meeting akan jauh lebih buruk.
- **Kecepatan CPU** (benchmark Handy, Ryzen 4750U; [sumber](https://models.handy.computer/)):

  | Model | CPU (x real time) | iGPU Vulkan (x real time) |
  |---|---|---|
  | Whisper large-v3-turbo | 0,8 (lebih lambat dari real time) | 3,4 |
  | Qwen3-ASR-0.6B | 4,3 | tidak dicatat |
  | Qwen3-ASR-1.7B | 2,0 | tidak dicatat |

- **Runtime:**
  - whisper.cpp **v1.9.5** (2026-10-06, MIT, VAD Silero bawaan)
  - **transcribe.cpp** (handy-computer, MIT, runtime ggml baru 2026 untuk 16+ keluarga model termasuk Qwen3-ASR dan Whisper; Metal/CUDA/Vulkan; binding Rust/TS/Swift)
  - sherpa-onnx **v1.13.8** (Apache-2.0)
- **Catatan penting:** Qwen3-ForcedAligner (timestamp per kata) **tidak mencantumkan Bahasa Indonesia**, dan streaming resmi Qwen3-ASR hanya lewat vLLM.
- **Code-switching ID-EN:** tidak ada benchmark publik untuk meeting. Riset akademiknya tipis (SIGUL 2024). Recap harus membangun korpus evaluasi sendiri.

### 6.2 VAD dan diarization

- **VAD:** Silero VAD **v6.2.3** (MIT, sekitar 2 MB, frame 32 ms). TEN VAD **dihindari** karena lisensinya melarang penggunaan yang bersaing dengan Agora.
- **Diarization:**
  - **sherpa-onnx** (segmentasi pyannote 3.0 + embedding 3D-Speaker/WeSpeaker + clustering) cocok untuk desktop tanpa Python.
  - pyannote community-1 (CC-BY-4.0, gated, hanya Python).
  - NVIDIA Streaming Sortformer / Nemotron-3-Diarization (GPU NVIDIA; lisensi Nemotron **perlu diverifikasi**).
  - DiariZen **tidak bisa dipakai** (bobotnya CC BY-NC).
  - **Tidak ada angka kecepatan CPU yang otoritatif**, jadi harus di-benchmark.

### 6.3 LLM lokal

- **Runtime:** llama.cpp **v0.6.0** (2026-10-05; kini memakai versi semver), binding Rust `llama-cpp-2 0.1.159`, dan konversi JSON schema ke grammar. Ollama v0.40.1 mendukung JSON schema pada `format`.
- **Model kecil dengan bukti kemampuan Bahasa Indonesia** (leaderboard SEA-HELM tertanggal 2026-09-18; angka diparsing sub-agent dari data halaman dan **perlu diverifikasi**):

  | Model | Skor ID | Lisensi |
  |---|---|---|
  | Gemma 4 12B | 74,5 | Apache-2.0 |
  | Qwen3.5-9B | 74,2 | Apache-2.0 |
  | Qwen3.5-4B | 69,7 | Apache-2.0 |
  | Llama-3.1-8B (pembanding) | 54,5 | Llama 3.1 |

  Keberadaan model Qwen3.5-4B/9B dan Gemma 4 12B di Hugging Face sudah saya konfirmasi.
- **Embedding:** Qwen3-Embedding-0.6B (Apache-2.0, GGUF) atau multilingual-e5-small (MIT).

### 6.4 Platform, distribusi, dan legal

- **Windows:**
  - **Process loopback** (`AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS`, mode EXCLUDE) tidak terikat device default dan tidak menangkap suara Recap sendiri.
  - Dokumentasi menyebut build 20348; dalam praktik berjalan di Windows 10 2004 yang sudah di-update (OBS, OpenWhispr).
  - Loopback **tidak mengirim paket saat hening**, jadi celah harus diisi.
  - Mode exclusive dan audio ber-DRM tidak tertangkap.
  - Headset Bluetooth turun ke HFP saat mic-nya dipakai.
- **macOS:**
  - Core Audio process tap (14.2+), dengan izin "System Audio Recording Only" dan `NSAudioCaptureUsageDescription`.
  - **Tidak ada API publik** untuk mengecek izin tap.
  - ScreenCaptureKit sebagai fallback butuh izin Screen Recording, yang di Sequoia diminta ulang secara berkala.
  - Mic butuh entitlement `com.apple.security.device.audio-input` di Hardened Runtime.
- **Linux:** monitor PipeWire, fallback PulseAudio `.monitor`. Belum ada portal izin audio.
- **Versi framework:** Tauri **v2.12.1** (2026-09-30; v3 masih alpha dengan opsi runtime CEF). Electron **v44.7.0**.
- **Code signing:**
  - **Azure Artifact Signing tidak tersedia untuk Indonesia.** Saya cek langsung di quickstart Microsoft (2026-10-08): organisasi hanya dari US, CA, EU, UK, AU, NZ, JP, KR, SG, CH, NO, dan IL; individu hanya dari US dan CA.
  - Alternatifnya: SignPath Foundation (gratis untuk OSS), sertifikat OV dengan cloud HSM (sekitar USD 150 sampai 300 per tahun), atau Microsoft Store.
  - Apple Developer Program USD 99 per tahun.
- **Import URL:**
  - yt-dlp **2026.08.19** (Unlicense) sering rusak (sekitar 10 rilis dalam 8 bulan 2026).
  - Untuk YouTube kini butuh runtime JS (Deno direkomendasikan) dan kadang PO token.
  - Mengunduh melanggar ToS YouTube. Status Pasal 52 UU 28/2014 (sarana kontrol teknologi) abu-abu.
- **ffmpeg:** gunakan build **LGPL**, jangan GPL.
- **Consent perekaman:**
  - Di Indonesia, perekaman oleh peserta umumnya tidak dianggap intersepsi menurut UU ITE Pasal 31, tetapi bisa digugat perdata.
  - UU PDP mengecualikan kegiatan pribadi/rumah tangga (Pasal 2 ayat 2), dan voiceprint berpotensi menjadi data biometrik (Pasal 4).
  - Di AS ada 11 negara bagian dengan aturan all-party consent, dan ada gugatan kelompok terhadap Otter.ai.

## 7. Pelajaran yang dipakai Recap

### 7.1 Diambil (dengan atribusi)

1. **Kanal terpisah dari ujung ke ujung** (prismical), bukan dicampur sebelum STT (kesalahan meetily). Hasilnya: label "Saya vs Peserta" gratis dan dasar untuk diarization.
2. **WebRTC AEC3 dengan system audio sebagai referensi** dan holdback mic sekitar 300 ms (`[P] Aec3Bridge`, `webrtc-aec3-builder`). Di Rust tersedia crate `webrtc-audio-processing` (BSD-3).
3. **Core Audio process tap yang mengecualikan PID sendiri** (prismical, cidre di meetily dan Anarlog).
4. **Process loopback Windows mode EXCLUDE** dan injeksi sunyi saat tidak ada render (OpenWhispr).
5. **Rekaman crash-safe:**
   - file per kanal dengan flush tiap 1 detik dan recovery header (Anarlog)
   - outbox/job tahan crash yang ditulis sebelum device dibuka, ID segmen deterministik (prismical)
6. **Isolasi komponen native di sidecar** (`llama-helper` meetily, worker whisper prismical), diperluas ke STT karena crash STT di meetily menjatuhkan aplikasi.
7. **Pelajaran VAD:**
   - segmen live terlalu pendek memicu halusinasi
   - redemption live sekitar 500 ms vs batch sekitar 2000 ms
   - potong paksa segmen panjang
   - potong batch di titik energi terendah (meetily)
8. **Perbaikan whisper.cpp:** patch `no_speech_prob`, deteksi bahasa terbatas `[id, en]`, dan filter halusinasi (prismical/amical, meetily).
9. **Prompt:** prompt ringkasan dengan aturan fidelitas dan aturan bahasa output untuk transkrip campuran (prismical); template berbasis bagian dengan rujukan timestamp (meetily).
10. **Tangga fallback structured output** untuk model lokal (prismical), plus field `nullable` agar kompatibel dengan OpenAI strict.
11. **Map-reduce dengan overlap** untuk model berkonteks kecil (meetily), diperluas menjadi hierarkis untuk semua provider.
12. **Kolom backup ringkasan** agar regenerasi aman (meetily); re-transkripsi dengan model atau bahasa lain (meetily).
13. **Downloader model yang bisa dilanjutkan** dan tervalidasi (meetily), ditingkatkan dengan SHA-256.
14. **Build ggml portabel** (`GGML_NATIVE OFF`), varian Vulkan di Windows dengan probe runtime dan fallback CPU (meetily, amical).
15. **Deteksi meeting** dari pemakaian mic per proses, hanya berupa prompt (prismical).
16. **Pre-roll** agar kata pertama tidak hilang (amical #179); downmix semua kanal input (amical #165).

### 7.2 Tidak ditiru

| Jangan | Sumber | Alasan |
|---|---|---|
| Mencampur mic + system sebelum STT | meetily | Kehilangan atribusi, gema ganda |
| DSP, mutex, dan alokasi di callback real-time | meetily | Glitch dan xrun |
| Menghapus `-wal`/`-shm` saat DB error | meetily | Kehilangan data diam-diam |
| API key plaintext di DB | meetily | Gunakan keychain OS |
| Frontend memegang data transkrip saat rekaman | meetily | Rapuh terhadap reload/crash WebView |
| Parakeet sebagai default; auto-detect bahasa per segmen | meetily | Tidak mendukung Indonesia; bahasa berganti-ganti |
| Antrean tanpa batas | meetily | Backlog tak terkendali |
| Unduhan binary/model tanpa hash | meetily | Risiko supply chain |
| Menggabungkan AAC 30 detik sebagai master | meetily | Artefak di batas chunk; bukan format yang crash-safe |
| Lapisan "local backend" yang mengemulasikan REST cloud | prismical | Kompleksitas tanpa manfaat untuk aplikasi lokal |
| Effect di seluruh main process, Yjs untuk catatan | prismical | Terlalu berat untuk tim solo |
| Menghapus audio setelah transkripsi | prismical | Kehilangan playback, re-transkripsi, ekspor |
| Chunk 15 detik tanpa overlap dan satu segmen per chunk | prismical | Latensi tinggi, kata di batas hilang |
| Tokenizer FTS porter | prismical | Khusus bahasa Inggris |
| Windows endpoint loopback tanpa exclude diri sendiri | prismical, meetily | Menangkap suara aplikasi sendiri dan notifikasi |
| Bundel binary Node tambahan; helper .NET self-contained | prismical | Ukuran installer |
| Feed update di backend proprietary | prismical | Gunakan GitHub Releases |

## 8. Implikasi lisensi untuk Recap

| Sumber | Lisensi | Boleh diambil? | Syarat |
|---|---|---|---|
| meetily | MIT | Ya | Sertakan copyright di `THIRD_PARTY_NOTICES`. Hindari bagian turunan Screenpipe sampai diverifikasi |
| prismical, amical | MIT | Ya | Sama |
| WebRTC AEC3 | BSD-3 + patent grant (+ abseil Apache-2.0) | Ya | Sertakan lisensi dan notice |
| whisper.cpp, llama.cpp, ggml | MIT | Ya | Notice |
| sherpa-onnx | Apache-2.0 | Ya | Notice + NOTICE file |
| Model Whisper, Silero VAD | MIT | Ya | Notice |
| Qwen3-ASR, Qwen3.5, Gemma 4, Qwen3-Embedding | Apache-2.0 | Ya | Notice; diunduh saat dibutuhkan, tidak dibundel |
| Parakeet, pyannote community-1 | CC-BY-4.0 | Ya, dengan atribusi | Atribusi di UI dan notice; pyannote gated |
| Gemma 3, EmbeddingGemma | Gemma Terms | Hindari sebagai default | Ada batasan penggunaan |
| DiariZen | CC BY-NC | **Tidak** | Non-komersial |
| noScribe, BlackHole | GPL-3.0 | **Tidak** (kecuali Recap GPL) | |
| Natively | Source-available non-komersial | **Tidak** | |
| TEN VAD | Apache-2.0 + klausul non-compete | Hindari | |
| ffmpeg | LGPL (build LGPL) | Ya, sebagai sidecar | Sediakan source dan configure line; jangan pakai build GPL |
| yt-dlp | Unlicense | Ya | Diunduh terpisah |

Karena Recap akan open source (keputusan klarifikasi), rekomendasi lisensinya adalah **MIT OR Apache-2.0** (dual, mengikuti konvensi ekosistem Rust). Detail ada di ADR-021 dokumen 04.
