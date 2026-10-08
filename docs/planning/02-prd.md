# 02. Product Requirements Document (PRD): Recap

## 1. Ringkasan produk

Recap adalah aplikasi desktop open source yang **MVP-nya khusus Windows** (keputusan 2026-10-08; macOS dan Linux menyusul setelah MVP), yang merekam dan memahami meeting, lalu menghasilkan catatan terstruktur:
- transkrip bertimestamp per pembicara
- ringkasan
- poin penting
- keputusan
- to-do dengan penanggung jawab dan tenggat
- pertanyaan terbuka, risiko, agenda berikutnya, dan chapter

Recap bekerja **sepenuhnya di perangkat** secara default, dengan dukungan utama **Bahasa Indonesia, Inggris, dan campuran keduanya**. Provider cloud bersifat opsional dan memakai key milik pengguna sendiri (BYOK).

**Diferensiasi** dibanding referensi (dokumen 01):
1. Indonesia-first, termasuk code-switching.
2. Kanal "Saya vs Peserta" sejak awal.
3. Rekaman tahan crash yang tetap menyimpan audio.
4. Ringkasan JSON dengan bukti yang bisa diklik.
5. Pencarian dan chat lintas meeting secara lokal.
6. Berjalan di laptop 8 GB tanpa GPU.

## 2. Masalah

- Notetaker AI populer (Otter, Fireflies, Granola, dan sejenisnya) mengirim audio ke cloud. Banyak organisasi dan profesional di Indonesia tidak boleh atau tidak mau melakukannya.
- Notetaker lokal yang ada:
  - lemah untuk Bahasa Indonesia (default model Inggris, auto-detect bahasa per potongan)
  - mencampur suara sendiri dan peserta
  - kehilangan data saat crash
  - tidak punya UI berbahasa Indonesia
- Meeting di Indonesia sering bercampur bahasa ("jadi kita perlu *align* dulu sama *stakeholder*") dan berlangsung panjang (2 sampai 3 jam).

## 3. Persona

| Persona | Profil | Kebutuhan utama | Hambatan |
|---|---|---|---|
| **Rani**, Product Manager startup (Jakarta) | 4 sampai 6 meeting online per hari di Zoom/Meet; bahasa campur ID-EN; laptop kantor 16 GB | Action item dan keputusan cepat setelah meeting; cari "kapan kita putuskan X?" | Kebijakan kantor melarang upload rekaman ke layanan pihak ketiga |
| **Pak Budi**, ASN / staf pemerintahan daerah | Rapat tatap muka 2 sampai 3 jam; laptop 8 GB tanpa GPU; mayoritas Bahasa Indonesia formal | Notulen rapat lengkap dengan daftar keputusan dan penanggung jawab | Tidak teknis; koneksi internet tidak stabil; data dinas sensitif |
| **Sari**, mahasiswa S2 / peneliti kualitatif | Wawancara narasumber dan kuliah; sering mengolah rekaman lama dan video kuliah | Transkrip akurat untuk analisis; ekspor DOCX; import file dan URL | Anggaran nol; etika penelitian mewajibkan data tidak keluar perangkat |
| **Dimas**, konsultan / jurnalis | Wawancara klien dan narasumber, campur online dan tatap muka; privasi narasumber | Kutipan akurat bertimestamp; pencarian lintas wawancara | Kerahasiaan sumber |

## 4. User stories

Prioritas: **M** = MVP, **B** = Beta, **L** = Later (rilis 1.0 atau setelahnya).

### 4.1 Merekam

| ID | Sebagai | Saya ingin | Agar | Prioritas |
|---|---|---|---|---|
| US-01 | Pengguna meeting tatap muka | merekam dari mikrofon dengan satu klik | rapat terdokumentasi tanpa persiapan | M |
| US-02 | Pengguna meeting online | merekam suara peserta (system audio) dan suara saya | percakapan dua arah tercatat | M |
| US-03 | Pengguna | memilih sumber aktif (mic saja, system saja, atau keduanya) dan device mic | sesuai situasi | M |
| US-04 | Pengguna | melihat level audio tiap sumber dan peringatan bila satu sumber sunyi atau izin belum diberikan | tidak menyadari kegagalan setelah rapat selesai | M |
| US-05 | Pengguna | jeda dan lanjutkan rekaman | bagian off-record tidak terekam | M |
| US-06 | Pengguna | rekaman tetap aman bila aplikasi crash atau laptop mati | rapat 3 jam tidak hilang | M |
| US-07 | Pengguna | diingatkan memberi tahu peserta dan bisa menyalin pesan pemberitahuan | etis dan patuh hukum | M |
| US-08 | Pengguna | melihat transkrip draf berjalan selama meeting (bisa dimatikan) | bisa mengikuti atau menandai momen penting | M |
| US-09 | Pengguna | menandai momen penting (bookmark) dan mengetik catatan singkat saat merekam | catatan pribadi masuk ke ringkasan | B |
| US-10 | Pengguna | diberi saran merekam saat aplikasi meeting memakai mikrofon | tidak lupa merekam | L |

### 4.2 Import

| ID | Sebagai | Saya ingin | Agar | Prioritas |
|---|---|---|---|---|
| US-11 | Peneliti | mengimpor file audio/video lokal (mp3, m4a, wav, mp4, mkv, webm, opus WhatsApp) | rekaman lama ikut diproses | M |
| US-12 | Pengguna | mengimpor beberapa file sekaligus ke antrean | efisien | B |
| US-13 | Mahasiswa | mengimpor dari URL (YouTube dan sumber yang didukung) dengan peringatan hak cipta/ToS | memproses kuliah publik | B (eksperimental) |

### 4.3 Transkrip dan pemahaman

| ID | Sebagai | Saya ingin | Agar | Prioritas |
|---|---|---|---|---|
| US-14 | Pengguna | transkrip bertimestamp dengan label "Saya" dan "Peserta" | tahu siapa berbicara | M |
| US-15 | Pengguna | membedakan beberapa peserta (Pembicara 1, 2, ...) dan memberi nama | notulen per orang | B |
| US-16 | Pengguna | memilih bahasa meeting (Indonesia campur Inggris, Inggris, lainnya) | transkrip akurat | M |
| US-17 | Pengguna | memperbaiki teks transkrip dan nama pembicara | hasil akhir benar | M (teks), B (speaker) |
| US-18 | Pengguna | mendaftarkan istilah atau nama (glosarium) | nama produk dan orang dieja benar | B |
| US-19 | Pengguna | memproses ulang dengan model atau bahasa lain | memperbaiki hasil buruk | M |
| US-20 | Pengguna | klik timestamp untuk memutar audio di titik itu | verifikasi cepat | M |

### 4.4 Ringkasan dan output

| ID | Sebagai | Saya ingin | Agar | Prioritas |
|---|---|---|---|---|
| US-21 | Pengguna | ringkasan otomatis, poin penting, keputusan, dan to-do (penanggung jawab + tenggat bila disebut) | tidak perlu menulis notulen | M |
| US-22 | Pengguna | setiap poin punya tautan bukti ke bagian transkrip | bisa memeriksa kebenaran | M |
| US-23 | Pengguna | pertanyaan terbuka, risiko, agenda berikutnya, dan chapter topik | tindak lanjut lebih baik | M (pertanyaan, agenda), B (risiko, chapter) |
| US-24 | Pengguna | memilih template (rapat umum, standup, wawancara, kuliah) | struktur sesuai konteks | B |
| US-25 | Pengguna | mengedit ringkasan dan menandai to-do selesai | ringkasan jadi dokumen kerja | M (edit field), B (editor kaya) |
| US-26 | Pengguna | ekspor ke Markdown, TXT, SRT/VTT, dan salin ke clipboard | dibagikan lewat chat/email/wiki | M |
| US-27 | Pengguna | ekspor ke DOCX dan PDF yang rapi | notulen resmi | B |
| US-28 | Pengguna | melihat semua to-do dari semua meeting | daftar tugas terpusat | B |

### 4.5 Tanya jawab dan pencarian

| ID | Sebagai | Saya ingin | Agar | Prioritas |
|---|---|---|---|---|
| US-29 | Pengguna | mencari kata atau frasa di semua meeting | menemukan diskusi lama | M (kata kunci) |
| US-30 | Pengguna | bertanya ke satu meeting ("apa alasan launch diundur?") dan mendapat jawaban bersitasi | tidak perlu membaca ulang | B |
| US-31 | Pengguna | bertanya lintas meeting ("apa saja keputusan soal harga bulan ini?") | pengetahuan organisasi | B |
| US-32 | Pengguna | pencarian semantik (makna, bukan kata persis) | lebih mudah menemukan | B |

### 4.6 Privasi, pengaturan, dan performa

| ID | Sebagai | Saya ingin | Agar | Prioritas |
|---|---|---|---|---|
| US-33 | Pengguna | semua berjalan lokal tanpa akun | data tidak keluar | M |
| US-34 | Pengguna | memakai key cloud sendiri secara opsional, dengan persetujuan setiap kali data dikirim | kualitas lebih tinggi di mesin lemah | B (MVP boleh menyertakan LLM BYOK bila waktu cukup) |
| US-35 | Pengguna | onboarding memeriksa perangkat dan memilih model yang sesuai, lalu mengunduhnya dengan progres | tidak perlu paham model | M |
| US-36 | Pengguna | mengatur retensi audio dan transkrip, serta menghapus permanen | kontrol data | M |
| US-37 | Pengguna | UI dalam Bahasa Indonesia dan Inggris | nyaman | M |
| US-38 | Pengguna | aplikasi memberi tahu bila pemrosesan akan lama dan tetap bisa dipakai | tidak frustrasi | M |
| US-39 | Pengguna | update aplikasi otomatis dan aman | selalu terbaru | M |

## 5. Lingkup fitur per fase

| Area | MVP | Beta | Rilis 1.0 dan setelahnya |
|---|---|---|---|
| Platform | Windows 10 2004+/11 x64 saja | Windows, plus perbaikan dari umpan balik | macOS 14.2+ arm64 (port, waktunya diputuskan setelah Beta); Linux (AppImage/deb, lalu Flatpak) |
| Capture | Mic, system, keduanya; pilih device; level meter; jeda; pre-roll; recovery | AEC3 (bila belum lulus di MVP); bookmark | Deteksi meeting (saran) |
| Import | File lokal via ffmpeg | Batch import; URL eksperimental | Watch folder |
| STT | Draf live + final pass; mode bahasa; re-transkripsi; edit teks | Glosarium; timestamp kata; highlight saat playback | Kosakata otomatis |
| Speaker | Saya vs Peserta (kanal) | Diarization offline multi-speaker; rename/merge | "Kenali suara saya" opt-in |
| Ringkasan | JSON: summary, poin, keputusan, to-do, pertanyaan terbuka, agenda; bukti; edit field | Risiko, chapter; template; editor kaya; daftar to-do lintas meeting | Template buatan pengguna |
| Cari dan chat | FTS5 kata kunci | Chat per meeting dan lintas meeting; hybrid semantic search | |
| Ekspor | MD, TXT, SRT, VTT, clipboard | DOCX, PDF, audio | Integrasi (Notion, Obsidian) via file |
| Cloud BYOK | Tidak ada (opsional bila waktu cukup: LLM saja) | LLM + STT BYOK dengan persetujuan | |
| Privasi | Lokal, keychain, retensi, pengingat consent | Halaman privasi lengkap | Vault terenkripsi opt-in |
| Distribusi | Installer bertanda tangan, auto-update | Kanal beta publik | Microsoft Store/winget, Homebrew cask |

## 6. Non-goals

1. **Bot yang ikut ke dalam meeting** (seperti Otter/Fireflies). Recap merekam dari perangkat pengguna.
2. **Rekaman video atau layar.**
3. **Terjemahan real-time atau teks terjemahan live** (bisa dipertimbangkan setelah 1.0).
4. **Kolaborasi tim, sinkronisasi cloud, atau akun.** Berbagi dilakukan lewat ekspor.
5. **Aplikasi mobile atau web.**
6. **Diarization real-time** yang akurat untuk banyak pembicara. Label live cukup Saya/Peserta.
7. **Coaching AI live** atau saran jawaban selama meeting.
8. **Integrasi kalender** di MVP dan Beta.
9. **Mendukung semua bahasa dengan kualitas setara.** Fokusnya ID dan EN; bahasa lain bersifat best-effort lewat Whisper.
10. **Menjamin legalitas perekaman** bagi pengguna. Recap hanya membantu lewat pengingat dan template.

## 7. Kebutuhan non-fungsional

| Kategori | Kebutuhan | Cara ukur |
|---|---|---|
| Keandalan rekaman | Kehilangan audio karena crash aplikasi 2 detik atau kurang; rekaman 3 jam tanpa dropout lebih dari 100 ms | Uji kill -9 dan uji endurance (S1, S10) |
| Sinkronisasi | Selisih mic vs system setelah koreksi 50 ms atau kurang selama 2 jam | Uji tone/klik (S1) |
| Sumber daya saat merekam | CPU Recap di bawah 15% (draf live aktif, tier standar), 40% atau kurang (draf live aktif, tier hemat), atau di bawah 5% (draf mati); RAM aplikasi di bawah 1,5 GB termasuk model draf | Profiling (S5, S10) |
| Waktu proses | Final pass + ringkasan untuk meeting 1 jam: 50 menit atau kurang di tier hemat (RTF final 0,5 + ringkasan 20 menit), 25 menit atau kurang di tier standar (RTF 0,25 + ringkasan 10 menit) | Benchmark (S4, S6) |
| Akurasi | Lihat target metrik di dokumen 05, bagian 5.2 | Korpus evaluasi |
| Ukuran installer | Di bawah 80 MB tanpa model (ffmpeg on-demand atau dibundel) | CI |
| Startup | Aplikasi siap dalam 3 detik atau kurang (tanpa memuat model) | CI dan manual |
| Aksesibilitas | Navigasi keyboard penuh, label screen reader, kontras WCAG AA | Audit (dokumen 07) |
| Privasi | Nol request jaringan tanpa tindakan pengguna (kecuali cek update yang bisa dimatikan) | Uji jaringan (proxy) di CI/manual |

## 8. Metrik keberhasilan

Recap tidak memakai telemetri. Metrik diukur dari pengujian internal, beta tester yang mengirim laporan sukarela (form/issue), dan statistik publik (unduhan GitHub, issue).

| Metrik | Target Beta | Target 1.0 | Sumber |
|---|---|---|---|
| Rekaman selesai tanpa kehilangan data | 99% atau lebih sesi beta tester | 99,5% atau lebih | Laporan beta + uji endurance |
| Crash-free sessions | 98% atau lebih | 99,5% atau lebih | Laporan crash manual |
| WER final (korpus ID-meeting) | 20% atau kurang (hemat), 15% atau kurang (standar) | 15% / 12% | Evaluasi |
| Recall action item | 80% atau lebih | 85% atau lebih | Evaluasi |
| Owner/tenggat karangan | 0 di set uji | 0 | Evaluasi |
| Tingkat edit ringkasan (porsi field yang diubah pengguna) | Di bawah 30% | Di bawah 20% | Survei beta |
| Waktu sampai catatan siap (meeting 1 jam, tier standar) | 25 menit atau kurang | 15 menit atau kurang | Benchmark |
| Aktivasi: pengguna baru berhasil merekam + mendapat ringkasan di hari pertama | 70% atau lebih beta tester | 80% atau lebih | Survei onboarding |
| Kepuasan (skala 1 sampai 5) untuk Bahasa Indonesia | 4 atau lebih | 4,3 atau lebih | Survei |
| Komunitas | 20 beta tester aktif | 500 bintang GitHub / 2.000 unduhan (indikatif) | GitHub |

## 9. Asumsi dan pertanyaan terbuka

- **Model:** Qwen3-ASR dan Qwen3.5 diasumsikan memberi kualitas Indonesia terbaik di ukuran kecil. Ini harus dibuktikan (S4, S6).
- **Sumber daya developer:** solo paruh waktu. Roadmap (dokumen 08) memakai rentang waktu lebar, dan lingkup Beta bisa dipangkas.
- **Nama produk** "Recap" perlu dicek ketersediaan merek dan domainnya (**perlu diverifikasi**).
- **Biaya tahunan:** untuk MVP Windows, mungkin sertifikat OV bila SignPath belum menerima proyek. Apple Developer (USD 99/tahun) baru dibutuhkan saat port macOS.
- **Kanal komunitas** untuk beta tester (Discord/Telegram/GitHub Discussions) belum ditentukan.
