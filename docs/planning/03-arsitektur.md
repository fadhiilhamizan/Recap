# 03. Arsitektur Sistem

Dokumen ini menjabarkan arsitektur Recap berdasarkan keputusan di dokumen 04, terutama ADR-003 (model proses dan IPC).

**Cakupan platform:** MVP khusus Windows (keputusan 2026-10-08). Bagian yang menyebut macOS adalah rancangan untuk port pasca-MVP, dipertahankan agar batas modul per OS sudah benar sejak awal.

## 1. Prinsip arsitektur

1. **Disk dulu, proses kemudian.** Audio mentah ditulis ke disk per kanal sebelum diproses apa pun. Semua pemrosesan lain (draf live, final pass, ringkasan) bisa diulang dari disk.
2. **Kanal terpisah dari ujung ke ujung.** Mic dan system tidak pernah dicampur, kecuali untuk playback dan ekspor.
3. **Isolasi kegagalan.** Komponen native berisiko (capture OS, ggml/ONNX) berjalan di sidecar. Crash satu sidecar tidak mematikan rekaman atau UI.
4. **Proses utama adalah satu-satunya pemilik data.** UI hanya menampilkan. Sidecar tidak menulis ke database.
5. **Job tahan crash.** Semua pekerjaan setelah rekaman adalah job di antrean SQLite yang bisa dilanjutkan setelah aplikasi dibuka ulang.
6. **Satu model berat di memori pada satu waktu** di tier hemat, diatur oleh scheduler sumber daya.
7. **Lokal secara default.** Komponen jaringan hanya aktif bila pengguna mengaktifkan provider cloud, import URL, atau unduhan model.

## 2. Gambaran komponen

```mermaid
flowchart LR
  subgraph UI["WebView UI (React + TS)"]
    UIRec["Layar rekam dan live transcript"]
    UIMeet["Detail meeting: ringkasan, transkrip, chat"]
    UISet["Pengaturan, model, privasi"]
  end

  subgraph MAIN["Proses utama recap-app (Rust, Tauri)"]
    CMD["Command dan event API (tauri-specta)"]
    SES["Session manager (state machine rekaman)"]
    SUP["Process supervisor"]
    JOB["Job queue dan resource scheduler"]
    STO["Storage service (SQLite writer, file store)"]
    SRCH["Search service (FTS5, vektor)"]
    PROV["Provider registry (lokal dan cloud)"]
    MOD["Model manager (unduh, verifikasi)"]
    SEC["Settings dan secrets (keychain)"]
    EXP["Export service"]
  end

  subgraph SIDE["Sidecar"]
    CAP["recap-capture: mic dan system, AEC, tulis WAV"]
    ASR["recap-asr: VAD, STT, diarization"]
    LLM["recap-llm: LLM dan embedding"]
    FF["ffmpeg (LGPL): decode, encode Opus"]
    YT["yt-dlp + Deno (Beta, on-demand)"]
  end

  DB[("recap.db SQLite WAL")]
  FS[("File meeting: WAV, Opus, timeline")]
  MODELS[("Folder model")]
  CLOUD["Provider cloud BYOK (opsional)"]

  UI <--> CMD
  CMD --> SES
  CMD --> SRCH
  CMD --> EXP
  SES --> SUP
  JOB --> SUP
  SUP <--> CAP
  SUP <--> ASR
  SUP <--> LLM
  SUP <--> FF
  SUP <--> YT
  CAP --> FS
  ASR --> FS
  FF --> FS
  STO --> DB
  SES --> STO
  JOB --> STO
  SRCH --> DB
  MOD --> MODELS
  ASR --> MODELS
  LLM --> MODELS
  PROV --> CLOUD
  JOB --> PROV
  SEC --> PROV
```

### 2.1 Tanggung jawab komponen

| Komponen | Tanggung jawab | Tidak boleh |
|---|---|---|
| **UI (WebView)** | Tampilan, input pengguna, i18n, aksesibilitas | Menyimpan data primer; memanggil jaringan langsung (CSP ketat, `connect-src 'self'`) |
| **recap-app (proses utama)** | Satu-satunya penulis DB; orkestrasi sesi dan job; supervisi sidecar; relay audio live; panggilan HTTP ke provider cloud; keychain | Menjalankan inferensi ML atau kode capture OS |
| **recap-capture** | Membuka device; ring buffer lock-free; timestamp; isi celah; tulis WAV per kanal (flush 1 detik); resample 16 kHz; AEC; kirim frame 16 kHz ke proses utama | Menunggu konsumen mana pun (tidak pernah memblok karena konsumen lambat) |
| **recap-asr** | VAD per kanal; segmentasi; STT draf dan final; diarization (Beta); menghasilkan segmen | Menulis DB (hanya mengirim hasil) |
| **recap-llm** | Muat model GGUF; generate dengan grammar JSON; embedding | Akses jaringan |
| **ffmpeg** | Decode file import; encode arsip Opus; mix untuk ekspor | |
| **yt-dlp** (Beta) | Mengunduh audio dari URL | Memakai cookies browser |

### 2.2 Struktur monorepo (rencana)

```
recap/
  apps/desktop/
    src-tauri/            crate recap-app (proses utama)
    ui/                   React + Vite
  crates/
    recap-protocol/       frame IPC, tipe pesan, versi protokol
    recap-core/           tipe domain (Meeting, Segment, Job, ...)
    recap-store/          skema SQLite, migrasi, repository
    recap-audio/          WAV writer crash-safe, resampler, drift, gap fill
    recap-capture/        binary sidecar capture (modul per OS)
    recap-asr/            binary sidecar ASR (trait AsrEngine)
    recap-llm/            binary sidecar LLM (llama-cpp-2)
    recap-prompts/        prompt, JSON schema output, validator
  tools/
    eval/                 skrip benchmark WER/DER/ringkasan (boleh Python)
    corpus/               manifest korpus uji (audio tidak di-commit)
  docs/planning/
```

## 3. Pembagian proses dan threading

### 3.1 recap-capture

```mermaid
flowchart LR
  OSM["Callback OS: mic"] -->|"SPSC ring buffer, tanpa alokasi"| W1["Thread kerja mic"]
  OSS["Callback OS: system loopback/tap"] -->|"SPSC ring buffer"| W2["Thread kerja system"]
  W1 --> TS["Stempel host time, isi celah, downmix"]
  W2 --> TS
  TS --> WAV["Penulis WAV per kanal, flush 1 detik, chunk 5 menit"]
  TS --> RS["Resample ke 16 kHz (rubato)"]
  TS --> AEC["AEC3: referensi system, holdback mic 300 ms"]
  AEC --> RS
  RS --> OUT["Thread stdout: frame biner per kanal"]
  TS --> TL["timeline.jsonl"]
```

- **Callback OS hanya menyalin sample ke ring buffer** (crate `rtrb` atau `ringbuf`). Tidak ada mutex, alokasi, atau DSP di callback; ini pelajaran dari meetily.
- **Penulisan WAV** di thread terpisah dengan buffer memori. Bila disk lambat, data ditahan di memori dengan batas, misalnya 60 detik, lalu ditulis berurutan (pola Anarlog).
- **Pengisian celah:**
  - Celah loopback Windows (tidak ada paket saat hening) diisi sunyi berdasarkan selisih QPC.
  - Celah karena device berganti juga diisi sunyi dan dicatat di `timeline.jsonl`.
- **Pre-roll:** capture dimulai sebelum UI menampilkan "Merekam", dan 1 detik pertama disimpan (pelajaran amical #179).
- **Downmix semua kanal input** menjadi mono (pelajaran amical #165).
- **Kesehatan stream:** event `health` setiap 1 detik berisi level RMS per kanal, jumlah xrun, dan apakah system "sunyi total". Proses utama memakainya untuk peringatan izin/device.

### 3.2 recap-asr

- Thread penerima frame → VAD per kanal → antrean segmen **berbatas** → satu thread inferensi.
- Bila antrean draf tertinggal lebih dari 30 detik dari real time, worker beralih ke mode "lewati draf": segmen ditandai `pending_final` dan UI diberi tahu bahwa draf tertunda. Capture tidak pernah diperlambat.
- Final pass membaca WAV langsung dari disk berdasarkan path dari proses utama; tidak lewat relay.

### 3.3 recap-llm

- Satu model termuat. Job diproses berurutan. Token di-stream ke proses utama untuk chat.
- Model di-unload saat idle, lewat timeout yang bisa diatur, misalnya 5 menit.

## 4. Strategi IPC

### 4.1 UI ↔ proses utama

- **Command** (request/response) untuk aksi: `start_recording`, `stop_recording`, `import_file`, `get_meeting`, `search`, `ask`, dan seterusnya.
- **Event/Channel** untuk stream: `level`, `segment_draft`, `job_progress`, `chat_token`, `health_warning`.
- Tipe di-generate oleh `tauri-specta` dari struct Rust menjadi TypeScript. Contract test di CI memastikan daftar command sesuai.
- Capability Tauri dibatasi: WebView tidak punya akses shell atau filesystem langsung.

### 4.2 Proses utama ↔ sidecar (`recap-protocol`)

Format frame di stdin/stdout:

```
u32  panjang frame (little endian, tidak termasuk 4 byte ini)
u8   jenis: 0 = JSON control, 1 = audio
...  payload
```

- **Payload JSON control:** `{"v":1,"id":"...","type":"...","data":{...}}`. Jenis pesan antara lain `hello`, `probe`, `start`, `stop`, `health`, `segment`, `error`, `progress`, `done`.
- **Payload audio:** header 32 byte (versi, kanal `mic|mic_aec|system`, format `f32le|s16le`, kanal fisik, sample rate, seq, sample_start u64, host_time_ns u64, panjang), lalu PCM.
- **Handshake:** `hello` berisi versi protokol dan versi binary. Bila tidak cocok, sidecar ditolak dan kesalahan instalasi dilaporkan.
- **Probe:** `recap-capture probe` dan `recap-asr probe` mengembalikan JSON kemampuan (device, dukungan process loopback, GPU yang terdeteksi, varian yang termuat). Dipakai saat onboarding dan diagnosa.
- **Stderr:** JSON lines untuk log, ditulis proses utama ke `logs/` (berotasi, maksimal misalnya 50 MB total, tanpa isi transkrip).
- **Golden test** format frame di CI (pola fixture prismical).

### 4.3 Supervisi

- Restart dengan backoff 1, 2, 4, 8, lalu 10 detik, maksimal 5 kali per sesi.
- **Circuit breaker ASR:** 2 crash beruntun dalam satu rekaman menghentikan draf live. Final pass tetap dicoba nanti sebagai job.
- **Capture crash:** proses utama me-restart capture dalam segmen file baru. Celah waktu dicatat di timeline dan ditampilkan sebagai penanda di transkrip.

## 5. Alur data

### 5.1 Alur data tingkat tinggi

```mermaid
flowchart TB
  subgraph Sumber
    MIC["Mikrofon"]
    SYS["System audio"]
    FILE["File audio/video"]
    URL["URL (Beta)"]
  end
  MIC --> CAP["recap-capture"]
  SYS --> CAP
  URL --> YTD["yt-dlp"] --> FILE
  FILE --> FFD["ffmpeg decode"]
  CAP --> RAW["WAV per kanal di disk"]
  CAP -->|"16 kHz live"| DRAFT["ASR draf live"]
  DRAFT --> SEGD["Segmen draf (DB)"]
  RAW --> FINAL["ASR final pass"]
  FFD --> FINAL
  FINAL --> SEGF["Segmen final (DB)"]
  SEGF --> DIAR["Diarization (Beta)"]
  DIAR --> SEGF
  SEGF --> SUM["Ringkasan JSON (LLM, map-reduce)"]
  SEGF --> IDX["Index FTS5 dan vektor"]
  SUM --> IDX
  RAW --> ARC["Arsip Opus"]
  IDX --> ASK["Chat dan pencarian"]
  SUM --> EXPO["Ekspor MD/SRT/DOCX/PDF"]
```

### 5.2 State machine sesi rekaman

```mermaid
stateDiagram-v2
  [*] --> Idle
  Idle --> Preparing: pengguna tekan Rekam
  Preparing --> Recording: izin dan device OK, outbox ditulis, capture siap
  Preparing --> Idle: dibatalkan atau gagal (pesan jelas)
  Recording --> Paused: jeda
  Paused --> Recording: lanjut
  Recording --> Stopping: berhenti
  Paused --> Stopping: berhenti
  Stopping --> Processing: file ditutup, job dibuat
  Processing --> Ready: semua job wajib selesai
  Processing --> NeedsAttention: job gagal setelah retry
  NeedsAttention --> Processing: coba lagi
  Ready --> Processing: proses ulang (model atau bahasa lain)
  Recording --> Recovering: aplikasi crash lalu dibuka lagi
  Recovering --> Processing: WAV dipulihkan
```

## 6. Sequence diagram

### 6.1 Sesi live (meeting online, dua sumber)

```mermaid
sequenceDiagram
  autonumber
  actor U as Pengguna
  participant UI as UI
  participant M as recap-app
  participant DB as SQLite
  participant C as recap-capture
  participant A as recap-asr
  participant L as recap-llm

  U->>UI: Pilih sumber (mic + system), bahasa, klik Rekam
  UI->>M: start_recording(opsi)
  M->>M: Cek ruang disk, tier, izin terakhir diketahui
  M->>DB: INSERT meeting (status=recording) dan job outbox
  M->>C: spawn + start(meeting_dir, sumber)
  C-->>M: started (device, sample rate, mode loopback)
  M->>A: spawn + start_live(model draf, bahasa, kanal)
  M-->>UI: event recording_started
  UI-->>U: Pengingat consent dan indikator merekam

  loop Setiap blok audio
    C->>C: Tulis WAV per kanal (flush 1 detik)
    C-->>M: frame audio 16 kHz (mic_aec, system)
    M->>A: relay frame
    C-->>M: health (level, xrun) tiap 1 detik
    M-->>UI: level meter
  end

  loop Setiap segmen VAD selesai
    A-->>M: segment(draft, kanal, start, end, teks)
    M->>DB: INSERT segment (is_draft=1)
    M-->>UI: segment_draft
  end

  U->>UI: Berhenti
  UI->>M: stop_recording
  M->>C: stop
  C->>C: Flush, tutup WAV, tulis header final
  C-->>M: stopped (durasi, file)
  M->>A: stop_live (flush segmen terakhir)
  M->>DB: UPDATE meeting status=processing, INSERT job final_asr, summarize, index, archive
  M->>A: final_asr(path WAV, model final)
  A-->>M: progress dan segmen final
  M->>DB: Ganti segmen draf dengan final (transaksi)
  M->>L: summarize(chunk transkrip, schema)
  L-->>M: JSON parsial per chunk, lalu JSON akhir
  M->>DB: INSERT summary dan action_item
  M-->>UI: meeting_ready
```

### 6.2 Import file

```mermaid
sequenceDiagram
  autonumber
  actor U as Pengguna
  participant UI as UI
  participant M as recap-app
  participant DB as SQLite
  participant F as ffmpeg
  participant A as recap-asr
  participant L as recap-llm

  U->>UI: Seret file atau pilih file
  UI->>M: import_file(path, bahasa, opsi)
  M->>F: probe (durasi, stream audio, codec)
  F-->>M: metadata
  M->>DB: INSERT meeting (source=file, status=processing) dan job
  M->>F: decode ke WAV 16 kHz mono (temp) dan encode arsip Opus
  F-->>M: progress lalu selesai
  M->>A: final_asr(path WAV, model final)
  A-->>M: progress dan segmen
  M->>DB: INSERT segment
  M->>L: summarize
  L-->>M: JSON ringkasan
  M->>DB: INSERT summary
  M->>M: Hapus WAV temp sesuai kebijakan
  M-->>UI: meeting_ready
```

Import URL (Beta) sama dengan import file, tetapi diawali langkah `yt-dlp` yang mengunduh `bestaudio` ke folder temp. Langkah ini punya progres sendiri dan error yang bisa dipahami pengguna, misalnya "Sumber berubah, perbarui komponen pengunduh".

### 6.3 Pemulihan setelah crash

```mermaid
sequenceDiagram
  participant M as recap-app
  participant DB as SQLite
  participant FS as File meeting
  participant A as recap-asr

  M->>DB: Saat start, cari meeting status=recording atau job belum selesai
  DB-->>M: daftar meeting yatim
  M->>FS: Periksa WAV per kanal, perbaiki header dari ukuran file
  M->>DB: Tandai meeting recovered, catat durasi yang dipulihkan
  M->>A: Lanjutkan job final_asr dari kursor terakhir
  M-->>M: Beri tahu pengguna: rekaman dipulihkan (durasi, celah)
```

### 6.4 Chat dengan transkrip (Beta)

```mermaid
sequenceDiagram
  actor U as Pengguna
  participant UI as UI
  participant M as recap-app
  participant L as recap-llm
  participant DB as SQLite

  U->>UI: Pertanyaan
  UI->>M: ask(meeting_id atau semua, pertanyaan)
  alt Transkrip muat di konteks
    M->>DB: Ambil transkrip dan ringkasan
  else Transkrip panjang atau lintas meeting
    M->>L: embed(pertanyaan)
    L-->>M: vektor
    M->>DB: Hybrid search (FTS5 + vektor), ambil top-k chunk
  end
  M->>L: generate(prompt dengan chunk bersitasi)
  L-->>M: token stream
  M-->>UI: chat_token (stream)
  M->>DB: Simpan pesan dan sitasi
```

## 7. Scheduler sumber daya

Aturan untuk tier hemat (8 GB):

| Situasi | Model termuat | Aturan |
|---|---|---|
| Merekam, draf live aktif | Model draf ASR kecil (sekitar 0,5 sampai 1 GB) | Tidak ada LLM. Embedding ditunda |
| Merekam, draf live dimatikan | Tidak ada | Hanya capture (CPU di bawah 5%) |
| Setelah rekaman | Model final ASR | Model draf di-unload dulu (proses `recap-asr` di-restart dengan model final) |
| Ringkasan | Model LLM | ASR di-unload (proses ASR dihentikan) |
| Indexing | Model embedding | Setelah ringkasan selesai, prioritas rendah |
| Rekaman baru saat job berjalan | Model draf | Job final/LLM dijeda (checkpoint), dilanjutkan setelah rekaman selesai |

Tier standar/kuat boleh menjalankan ASR dan LLM bersamaan bila RAM bebas melebihi ambang (misalnya model + 2 GB).

Scheduler membaca memori bebas (crate `sysinfo`) sebelum memuat model. Bila tidak cukup, ia menurunkan pilihan model sesuai tier dan memberi tahu pengguna.

## 8. Keamanan arsitektur (ringkas)

Detail ada di dokumen 06.

- **CSP WebView ketat.** Semua HTTP keluar lewat Rust, dengan allowlist host provider yang diaktifkan pengguna.
- **Sidecar dijalankan dengan path absolut** dari folder aplikasi, tanpa input shell.
- **Validasi input ffmpeg/yt-dlp:** argumen dibangun sebagai array dan URL divalidasi skemanya (`https`).
- **Unduhan model dan komponen** diverifikasi dengan SHA-256 dari katalog bertanda tangan.
- **Transkrip dianggap data tidak tepercaya di prompt LLM.** Guard terhadap prompt injection diterapkan, dan output divalidasi skema.

## 9. Keputusan terbuka yang dijawab spike

| Pertanyaan | Spike |
|---|---|
| Capture macOS: cidre atau helper Swift? Atribusi TCC untuk proses anak? | S2 (ditunda, pasca-MVP) |
| Apakah AEC3 cukup untuk target duplikasi? | S3 |
| Engine dan model final per tier? | S4 |
| Latensi draf live yang realistis per tier? | S5 |
| Model LLM default dan pass bahasa (langsung Indonesia atau Inggris lalu terjemah)? | S6 |
| Overhead relay audio di proses utama untuk 3 jam? | S10 |
