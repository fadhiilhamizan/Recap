# S0. Panduan Korpus Evaluasi

Korpus ini dipakai oleh semua spike kualitas (S4 STT, S5 latensi, S6 ringkasan, S7 diarization). Kualitas keputusan kita hanya sebaik korpus ini. **FLEURS (ucapan terbaca) tidak mewakili meeting nyata**, jadi korpus meeting Indonesia adalah bagian terpenting S0.

## 1. Target isi

| Set | Isi | Target durasi | Status |
|---|---|---|---|
| `fleurs-id` | FLEURS Bahasa Indonesia, split test, 200 kalimat (CC-BY-4.0) | 40 menit | **Siap** (`.data/corpus/fleurs-id/`) |
| `id-meeting` | Meeting nyata berbahasa Indonesia: minimal 2 jam online (mic dan suara peserta terpisah) + 2 jam tatap muka | 5 sampai 10 jam total | **Butuh rekaman dari pemilik produk** |
| `id-en` | Meeting padat campur Indonesia-Inggris (startup, IT, konsultan) | 2 jam (bagian dari `id-meeting`) | Butuh rekaman |
| `en-meeting` | AMI Meeting Corpus subset (CC-BY-4.0) | 2 jam | Menyusul (dipakai di S7 dan sebagai pembanding) |
| `hard` | Speaker laptop tanpa headset (gema), headset Bluetooth, ruangan bergema | 1 jam | Butuh rekaman |
| `silence` | Rekaman hening/ruang kosong/musik latar tanpa ucapan, untuk mengukur halusinasi | 10 sampai 20 menit | Bisa direkam sendiri kapan saja |

**Minimum agar S4 bisa diputuskan:** 2 jam `id-meeting`, termasuk sekitar 45 menit `id-en`, yang punya transkrip gold untuk minimal 1 jam.

## 2. Izin (wajib, sebelum merekam)

Setiap rekaman di korpus harus punya **izin tertulis dari semua peserta**. Simpan bukti izin (foto/scan formulir, atau pesan tertulis seperti email/chat) di luar repo. Manifest hanya mencatat jenis izinnya.

### Templat formulir izin

> **Persetujuan Penggunaan Rekaman untuk Pengujian Perangkat Lunak**
>
> Saya yang bertanda tangan di bawah ini menyetujui bahwa rekaman suara dari pertemuan "\_\_\_\_\_\_\_\_" pada tanggal \_\_\_\_\_\_\_\_ digunakan oleh \_\_\_\_\_\_\_\_ (pengembang Recap) **hanya untuk menguji dan mengukur akurasi perangkat lunak transkripsi dan ringkasan**.
>
> Ketentuan:
> 1. Rekaman, transkrip, dan catatannya disimpan secara lokal di perangkat pengembang, tidak diunggah ke layanan cloud, dan tidak dipublikasikan.
> 2. Rekaman tidak dipakai untuk melatih model AI.
> 3. Hasil pengujian yang dipublikasikan hanya berupa angka agregat (misalnya tingkat kesalahan kata), tanpa isi percakapan.
> 4. Saya dapat menarik persetujuan ini kapan saja, dan rekaman akan dihapus dalam 7 hari.
> 5. Rekaman akan dihapus paling lambat 2 tahun setelah tanggal ini.
>
> Nama: \_\_\_\_\_\_\_\_ Tanda tangan: \_\_\_\_\_\_\_\_ Tanggal: \_\_\_\_\_\_\_\_

Untuk meeting online, cukup pesan tertulis yang memuat poin 1 sampai 4 dan jawaban "setuju" dari setiap peserta.

**Jangan** memakai rekaman yang berisi data sangat sensitif (kesehatan, keuangan pribadi, data anak), meskipun sudah ada izin.

## 3. Cara merekam (sebelum aplikasi Recap ada)

**Meeting online (dua kanal terpisah)**, pilih salah satu:
- **OBS Studio** (gratis): tambahkan "Audio Input Capture" (mikrofon) dan "Application Audio Capture" (aplikasi meeting) sebagai dua track terpisah. Rekam ke MKV multi-track, lalu ekspor tiap track sebagai WAV.
- **Audacity**: rekam mikrofon saja, dan gunakan perekam bawaan aplikasi meeting (Zoom/Meet/Teams) untuk suara peserta. Selaraskan manual. Kurang ideal.

**Meeting tatap muka:** laptop di meja seperti pemakaian nyata (bukan mic khusus), dengan perekam bawaan Windows (Voice Recorder / Sound Recorder) atau Audacity, format WAV atau M4A.

**Catat untuk setiap rekaman:** jumlah peserta, perangkat (laptop/headset), lingkungan (ruang rapat/kafe/rumah), dan perkiraan porsi bahasa Inggris.

## 4. Konvensi transkrip gold

File gold berupa teks UTF-8 (`gold/<id>.txt`). Untuk `id-meeting`, satu baris per giliran bicara dengan timestamp opsional.

```
[00:12:31] A: oke jadi untuk {launch} kita mundurin ke tanggal 20 ya
[00:12:36] B: setuju tapi {QA} butuh dua hari buat {regression test}
```

Aturan:
1. **Tulis apa yang diucapkan**, bukan yang "seharusnya". Gunakan ejaan baku untuk kata baku, dan ejaan umum untuk kata tidak baku ("nggak", "udah", "gimana").
2. **Kata atau frasa bahasa Inggris** diapit kurung kurawal: `{deadline}`, `{follow up}`. Ini dipakai untuk menghitung CS-WER. Serapan yang sudah lazim dalam KBBI (misalnya "rapat", "target", "data") **tidak** diberi kurung.
3. **Angka** boleh ditulis sebagai digit atau kata; normalisasi menyamakannya.
4. **Bagian tidak jelas** diberi `[tidak jelas]`, dan suara non-ucapan `[tertawa]`, `[batuk]`, `[musik]`. Semua yang dalam kurung siku diabaikan saat penilaian.
5. **Kata pengisi** (eh, em, hmm) boleh ditulis atau tidak; normalisasi membuangnya.
6. **Ucapan bertumpuk:** tulis keduanya berurutan pada baris masing-masing.
7. **Label pembicara** (A, B, C) dipakai untuk S7; label `A` sebaiknya pemilik rekaman ("Saya").
8. Untuk menghemat waktu, transkrip gold boleh dibuat dengan **mengoreksi hasil model terbaik** baris per baris, sambil mendengarkan audio. Catat hal ini di manifest (`"gold_method": "corrected-from:<model>"`), karena metode ini sedikit menguntungkan model tersebut.

Untuk S4, label pembicara dan timestamp dibuang oleh skrip; yang dinilai adalah teksnya.

## 5. Anotasi ringkasan (untuk S6)

Untuk 10 meeting/potongan, buat `gold/<id>.summary.json`:

```json
{
  "decisions": ["Launch fitur pembayaran diundur ke 20 Oktober"],
  "action_items": [
    {"task": "Siapkan regression test pembayaran", "owner": "Dewi", "due_text": "Jumat depan"}
  ],
  "open_questions": ["Apakah vendor payment gateway siap di sandbox?"]
}
```

Hanya tulis item yang **benar-benar** disepakati atau ditugaskan secara eksplisit.

## 6. Struktur folder dan manifest

```
.data/corpus/                      (tidak pernah di-commit)
  fleurs-id/  audio/*.wav  manifest.jsonl
  id-meeting/ audio/<id>.wav (atau <id>.mic.wav + <id>.system.wav)  gold/<id>.txt  manifest.jsonl
  silence/    audio/*.wav  manifest.jsonl
```

Contoh baris manifest `id-meeting`:

```json
{"id": "rapat-2026-10-15-produk", "set": "id-en", "audio": "audio/rapat-2026-10-15-produk.system.wav", "ref_file": "gold/rapat-2026-10-15-produk.txt", "language": "id", "kind": "longform", "consent": "written-all-participants", "channel": "system", "participants": 4, "device": "laptop+headset-kabel", "gold_method": "manual"}
```

Untuk meeting dua kanal, buat **dua item** (`.mic` dan `.system`), masing-masing dengan gold untuk kanal itu. Ini sesuai desain Recap yang mentranskripsi kanal secara terpisah.

Setelah gold ditulis dengan label pembicara, ubah ke referensi teks polos dengan:

```
python scripts/gold_to_ref.py .data/corpus/id-meeting/gold/<id>.txt
```

(Skrip ini membuang timestamp dan label, lalu menulis `<id>.ref.txt`.)
