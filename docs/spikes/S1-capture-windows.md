# Spike S1: Capture Audio Windows (mic + system, dua track crash-safe)

Status: **Lulus bersyarat**. Fungsi inti, crash-safety, dan ketahanan ganti device (simulasi) lulus; tes manual T1 sampai T3 tertunda (bagian 6) · Mulai: 2026-10-10 · Diperbarui: 2026-10-26

## 1. Prototipe

`tools/spikes/s1-capture` (Rust, crate `wasapi` 0.25):
- **System audio:** WASAPI **process loopback** mode `EXCLUDE` pohon proses sendiri, sehingga suara Recap tidak ikut terekam. Fallback ke endpoint loopback (`--system endpoint`).
- **Mic:** WASAPI shared mode, perangkat default.
- **Format:** diminta 48 kHz mono f32 (autoconvert WASAPI), ditulis WAV 16-bit per kanal, dipotong per 5 menit, header di-flush tiap 1 detik.
- **Pengisian celah:** berdasarkan timestamp QPC paket, ditambah pengisian saat loopback tidak mengirim paket (hening). Ambang 20 ms; jitter lebih kecil tidak diisi.
- **Timeline:** `timeline.jsonl` mencatat QPC per paket untuk analisis drift.
- **Subcommand:** `probe`, `record`, `recover` (perbaiki header WAV setelah crash), dan `clicks` (pemutar klik dari proses terpisah untuk uji sinkronisasi).
- Analisis: `tools/eval/scripts/s1_analyze.py`.

Build: Rust 1.99 stable MSVC, VS Build Tools 17.14. Kompilasi bersih tanpa warning.

## 2. Lingkungan

Lenovo 83KX, Windows 11 Home build 26200. Mic: *Microphone Array (Intel Smart Sound Technology)*. Output: *Speakers (Realtek Audio)*.

## 3. Hasil uji

| Uji | Hasil | Status |
|---|---|---|
| Probe | Process loopback (exclude self) **tersedia** | Lulus |
| 2 menit + klik tiap 10 detik dari proses terpisah | Kanal system menangkap 12 klik **tepat tiap 10,000 detik**. Panjang kanal mic vs system selisih **3 ms**. Celah yang diisi hanya 1 sampai 2 (sekitar 0,2 detik di awal stream) | Lulus |
| 15 detik, pengguna berbicara | Mic menangkap ucapan (puncak -22 dBFS, rata-rata -40 dBFS). Transkripsi Qwen3-ASR: "tes satu dua tiga tes tes..." | Lulus |
| 2 menit, video YouTube diputar lewat speaker | System: -15 sampai -20 dBFS stabil, transkripsi Indonesia santai sangat baik. Selisih panjang kanal 8 ms. Mic: nol digital hampir sepanjang rekaman (lihat temuan 2) | Lulus (system) |
| Kill paksa di detik 37 (`TerminateProcess`) | WAV **langsung terbaca tanpa perbaikan**: header sudah benar (37,25 dan 37,22 detik vs 37,34 detik sejak proses diluncurkan), sehingga kehilangan **di bawah 0,2 detik**. `recover` berjalan aman. Baris terakhir `timeline.jsonl` terpotong (wajar, pembaca harus toleran) | Lulus (target 2 detik atau kurang) |
| Rekaman 3 jam, drift mic vs system pada menit 120 | Belum | Menunggu sesi panjang |
| Ganti device, Bluetooth, sleep/resume, Windows 10 | Belum | Menunggu |
| CPU proses capture di bawah 3% | Belum diukur formal | Menunggu uji 3 jam |

## 4. Temuan

1. **Process loopback EXCLUDE berfungsi di Windows 11** dan stabil. Paket datang tiap 10 ms (480 frame), dan jitter timestamp di bawah 20 ms tidak perlu diisi.
2. **Mic Intel Smart Sound memakai peredam bising dan AEC yang agresif di level driver/OS:**
   - Saat hening, sinyal turun ke sekitar -94 dBFS.
   - Saat video diputar lewat **speaker laptop**, mic mengirim **nol digital** (-240 dBFS): gema speaker sudah dihapus sebelum sampai ke aplikasi.
   - **Implikasi produk:**
     - (a) Detektor "mic mati" tidak boleh hanya melihat level. Ia harus membedakan "stream hidup tapi hening" dari "tidak ada paket/akses ditolak", dan baru memperingatkan setelah hening total cukup lama sementara kanal system aktif, dengan tombol "uji mic".
     - (b) Di laptop seperti ini AEC Recap mungkin tidak dibutuhkan, tetapi **tidak bisa diandalkan di semua laptop**. S3 tetap perlu diuji, idealnya juga di laptop tanpa AEC driver.
     - (c) Perlu diuji apakah suara pengguna tetap utuh saat berbicara bersamaan dengan video (double-talk), karena AEC driver kadang ikut memotong suara lokal.
3. **Level mic rendah** (rata-rata sekitar -40 dBFS saat bicara normal). STT tetap akurat, tetapi normalisasi level untuk jalur STT layak diuji di S4 tahap 2.
4. **Format hound + flush tiap 1 detik sudah cukup crash-safe**; recovery header hanya jaring pengaman.

## 5. Ketahanan terhadap perubahan device (diuji otomatis, 2026-10-26)

Tes manual ganti device ditunda sampai pemilik produk bisa melakukannya. Supaya perilakunya tetap terjamin, penanganannya diimplementasikan dan diuji otomatis dengan sumber audio palsu dan jam virtual (`tools/spikes/s1-capture/tests/device_change.rs`, jalankan `cargo test --release`).

**Mekanisme di prototipe** (`src/lib.rs`, fungsi `supervise`):
- **Supervisor per kanal** tidak pernah berhenti karena error device. Stream yang error (misalnya `AUDCLNT_E_DEVICE_INVALIDATED`) dibuka ulang dengan backoff 0,1 / 0,2 / 0,5 / 1 / 2 detik.
- **Ikut device default:** notifikasi Windows (`IMMNotificationClient`, role Console) memicu buka ulang mic, dengan debounce 300 ms. Mode endpoint loopback juga mengikuti device render default. **Process loopback tidak perlu dibuka ulang** karena tidak terikat device output.
- **Watchdog:** mic yang berhenti mengirim paket selama 2 detik dibuka ulang. Ini berbeda dari mic yang hening, yang tetap mengirim paket. Loopback hening dianggap wajar dan tidak dibuka ulang.
- **Timeline tetap mengikuti jam QPC:** waktu tanpa device diisi nol. Celah di atas 30 detik (sleep/resume) **tidak** diisi nol, tetapi dicatat sebagai `long_gap` di timeline dan dilanjutkan di file baru.
- Setiap `opened` (beserta nama device) dan `lost` (beserta alasan) dicatat di `timeline.jsonl`, sehingga UI nanti bisa menampilkan penanda di transkrip.

| Skenario simulasi | Yang diverifikasi | Hasil |
|---|---|---|
| Headset dicabut, 3 kali gagal dibuka, lalu pindah ke mic internal | Dicoba ulang sampai berhasil; timeline tetap 10 detik; celah sekitar 0,8 detik diisi nol sebagai 1 celah; 3 detik audio headset utuh, sampel demi sampel; nama device baru tercatat | Lulus |
| Device default berganti (misalnya ke headset Bluetooth Hands-Free) | Tepat 1 buka ulang; celah hanya selama debounce (sekitar 0,3 detik) | Lulus |
| Mic macet (stream hidup, paket berhenti) | Watchdog membuka ulang setelah 2 detik; timeline tetap sejajar jam | Lulus |
| Loopback hening 20 detik | **Tidak** dibuka ulang | Lulus |
| Sleep 1 jam lalu resume | Tidak menulis 1 jam nol (hanya sekitar 4 detik audio nyata); `long_gap` tercatat; file baru; posisi timeline tetap sesuai jam | Lulus |
| Mic putus sekitar 1,5 detik, system mengalir terus | Posisi akhir mic dan system selisih 20 ms atau kurang (tetap sejajar) | Lulus |

Regresi dengan WASAPI nyata setelah refaktor (10 detik): kedua kanal 10,0 detik, satu `opened` per kanal, tanpa buka ulang.

**Yang belum dibuktikan simulasi dan menunggu tes manual:**
- Perilaku nyata driver Windows saat headset dicolok: urutan notifikasi, apakah stream lama mengembalikan error atau diam.
- Format yang berubah, misalnya Bluetooth HFP 16 kHz. Ini seharusnya tertangani oleh autoconvert WASAPI ke 48 kHz.
- Waktu buka ulang nyata.

Karena semua jalur (error, macet, dan notifikasi) berakhir di mekanisme buka ulang yang sama dan sudah teruji, risiko yang tersisa terutama soal **lama celah**, bukan kehilangan rekaman.

## 6. Tes tertunda (menunggu pemilik produk)

| No | Tes | Kebutuhan | Kriteria lulus |
|---|---|---|---|
| T1 | Rekaman 2 sampai 3 jam + klik tiap 30 detik dari speaker | Sesi meeting atau video panjang | Drift mic vs system pada menit 120 50 ms atau kurang; tanpa dropout lebih dari 100 ms; CPU capture di bawah 3% |
| T2 | Double-talk: bicara sambil video diputar di speaker | 1 menit | Suara pengguna utuh di kanal mic (transkripsi benar), meski AEC driver aktif |
| T3 | Ganti device di tengah rekaman: colok/lepas headset, Bluetooth, ganti default di Sound Settings, sleep/resume | Headset kabel/Bluetooth | Rekaman tidak berhenti; celah per kejadian 2 detik atau kurang; `opened` dengan nama device baru tercatat |

## 7. Langkah berikutnya

1. **Uji 3 jam** (atau minimal 2 jam) saat meeting/video panjang, dengan `clicks` tiap 30 detik diputar lewat speaker untuk mengukur drift.
2. **Double-talk:** pengguna berbicara sambil video diputar di speaker; cek apakah suara pengguna utuh di kanal mic.
3. Ganti output (colok headset) di tengah rekaman; Bluetooth (perkiraan HFP); sleep/resume.
4. Ukur CPU proses capture.
5. Windows 10 (VM atau mesin lain) untuk memastikan process loopback tersedia di build 19041+.
