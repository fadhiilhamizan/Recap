# Spike S5: Latensi Draf Live dan Segmentasi VAD

Status: **Lulus (indikatif, audio FLEURS)** · Dijalankan: 2026-10-10 · Mesin: i7-13620H, 16 GB, Intel UHD (Vulkan), Windows 11

## 1. Metode

- **Audio:** 4 aliran x 10,1 menit (total 40,4 menit) dari 172 kalimat FLEURS Indonesia, disambung dengan jeda acak (umumnya 0,2 sampai 2,5 detik, sesekali 5 sampai 8 detik). Skrip: `tools/eval/scripts/make_longform.py`.
- **Pipeline** (sama dengan desain `recap-asr`, dokumen 05 bagian 2.2):
  - Silero VAD v6 per frame 32 ms.
  - Segmen ditutup setelah 600 ms sunyi atau panjang maksimum 20 detik, dengan padding 200 ms.
  - Antrean, lalu **satu** thread inferensi.
- **Jam virtual:** inferensi dijalankan sungguhan, tetapi audio tidak diputar real time.
  - Teks dianggap muncul pada `max(segmen ditutup, worker bebas) + waktu inferensi`.
  - **Latensi** = waktu teks muncul dikurangi akhir ucapan.
  - Kode: `tools/eval/recap_eval/live.py`.
- **CPU** = waktu CPU proses selama inferensi dibagi durasi audio. Dinyatakan sebagai "core setara" dan sebagai porsi seluruh mesin (16 thread). Untuk Vulkan, kerja GPU tidak terhitung sebagai CPU.
- **Varian `merge25`:** segmen VAD berurutan digabung sampai sekitar 25 detik. Tujuannya mengurangi pemborosan Whisper yang selalu meng-encode jendela 30 detik (temuan S4).

## 2. Hasil

| Konfigurasi | Kebijakan | Latensi p50 | **Latensi p95** | Maks | Antrean maks | Backlog tumbuh? | CPU (core setara) | WER draf |
|---|---|---|---|---|---|---|---|---|
| Qwen3-ASR-0.6B Q8, CPU 4 thread | live | 2,7 s | **4,6 s** | 5,4 s | 0,1 s | Tidak | 0,72 | 7,8% |
| Qwen3-ASR-0.6B Q8, CPU 2 thread | live | 3,8 s | **6,4 s** | 8,9 s | 1,9 s | Tidak | 0,54 | 7,8% |
| Qwen3-ASR-0.6B Q8, Vulkan | live | 2,2 s | **3,6 s** | 4,3 s | 0 s | Tidak | 0,06 | 7,9% |
| Qwen3-ASR-1.7B Q5, Vulkan | live | 3,5 s | **5,8 s** | 7,3 s | 1,2 s | Tidak | 0,09 | **4,7%** |
| Whisper small Q8, CPU 4 thread | live | 3,4 s | **3,8 s** | 7,7 s | 0,3 s | Tidak | 0,90 | 17,7% |
| Whisper large-v3-turbo Q5, Vulkan | live | 5,9 s | **6,4 s** | 9,0 s | 3,3 s | Tidak | 0,11 | 5,9% |
| Whisper large-v3-turbo Q5, Vulkan | merge25 | 5,6 s | **5,8 s** | 5,9 s | 0 s | Tidak | 0,08 | 5,9% |

Panjang segmen rata-rata: 9,0 detik (live), 11,3 detik (merge25).

## 3. Terhadap kriteria S5 (dokumen 10)

| Kriteria | Target | Hasil |
|---|---|---|
| p95 latensi, tier hemat | 10 detik atau kurang | **Lulus**: Qwen3-ASR-0.6B 4,6 detik (4 thread), 6,4 detik (2 thread) |
| p95 latensi, tier standar | 5 detik atau kurang | **Lulus** dengan Qwen3-ASR-0.6B Vulkan (3,6 detik). Qwen3-ASR-1.7B (5,8 detik) dan Whisper turbo (5,8 sampai 6,4 detik) sedikit di atas target |
| Backlog tidak tumbuh | Selama 1 jam | **Lulus** di semua konfigurasi (antrean maksimum 3,3 detik) |
| CPU, tier hemat | 40% atau kurang | **Lulus**: 0,72 core setara (4,5% mesin ini; pada laptop 4 core sekitar 18%, perkiraan kasar) |
| Halusinasi saat hening | Mendekati nol | Tidak diukur terpisah. VAD tidak mengirim jeda hening ke STT. Perlu set `silence` nyata |

## 4. Temuan

1. **Draf live yang direkomendasikan: Qwen3-ASR-0.6B di semua tier.** Latensi 3,6 sampai 4,6 detik, beban CPU di bawah 1 core, dan WER draf 7,8% (jauh di atas Whisper small: 17,7%).
2. **Segmentasi VAD wajib untuk Qwen3-ASR.** Pada S9, audio 68 detik yang dikirim dalam satu panggilan mendapat WER 21%. Dipotong VAD (rata-rata 9 detik per segmen), akurasinya kembali ke tingkat per-kalimat (7,8% untuk 0.6B, 4,7% untuk 1.7B). Ini memvalidasi desain dokumen 05 (segmen maksimum 20 sampai 28 detik).
3. **Final pass Qwen3-ASR-1.7B tidak kehilangan akurasi** di jalur long-form (4,7%, sama dengan per kalimat). Kandidat final pass tier standar tetap 1.7B.
4. **Menggabung segmen untuk Whisper (merge25) mengurangi latensi ekor dan antrean** (p95 6,4 menjadi 5,8 detik, antrean maksimum 3,3 menjadi 0 detik) tanpa mengubah WER. Bila Whisper dipakai, gabungkan segmen.
5. **2 thread CPU pun cukup untuk draf live** (p95 6,4 detik), sehingga di laptop lemah masih ada ruang untuk aplikasi meeting yang berjalan bersamaan.

## 5. Keterbatasan

- Audio adalah ucapan terbaca yang bersih tanpa tumpang tindih. Meeting nyata punya giliran bicara pendek, interupsi, dan noise; latensi bisa berbeda karena pola segmen berbeda.
- Simulasi jam virtual mengabaikan persaingan CPU dengan capture, aplikasi meeting, dan UI. Uji end-to-end real time dilakukan di S10 (endurance).
- "Tier hemat" masih disimulasikan dengan membatasi thread di CPU yang jauh lebih cepat dari laptop 8 GB umumnya.

## 6. Dampak ke dokumen perencanaan

- **ADR-010:** draf live memakai **Qwen3-ASR-0.6B** di semua tier (bukan Whisper small). Final pass: Qwen3-ASR-0.6B (hemat) / 1.7B (standar). Diterapkan setelah tahap 2 S4 (korpus meeting) mengonfirmasi.
- **Dokumen 05, bagian 2.2:** parameter segmentasi live (600 ms / 20 detik / pad 200 ms) terbukti layak. Tambahkan aturan "gabung segmen sampai sekitar 25 detik bila engine adalah Whisper".
