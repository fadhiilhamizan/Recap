# tools/eval: harness evaluasi Recap

Tooling untuk spike S0 (korpus + metrik) dan S4 (benchmark STT). **Bukan bagian produk**: produk ditulis dalam Rust (ADR-002), sedangkan tooling ini memakai Python agar cepat dibuat. Logika VAD/segmenter di sini sengaja meniru desain `recap-asr` (dokumen 05) supaya parameternya bisa dipindahkan.

## Setup (Windows)

```powershell
cd tools\eval
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pytest -q tests
```

Semua data besar (model, audio korpus, hasil) disimpan di `.data/` di root repo dan **tidak di-commit**.

## Langkah S0/S4

```powershell
# 1. Rencana unduhan + cek ruang disk, lalu unduh (SHA-256 diverifikasi, dicatat di .data/models/lock.json)
.venv\Scripts\python.exe scripts\download_models.py --groups base,s4,parity --dry-run
.venv\Scripts\python.exe scripts\download_models.py --groups base,s4,parity

# 2. Korpus pembanding FLEURS Indonesia (200 kalimat, sekitar 40 menit)
.venv\Scripts\python.exe scripts\prepare_fleurs.py --count 200

# 3. Benchmark satu konfigurasi
.venv\Scripts\python.exe -m recap_eval.bench --manifest ..\..\.data\corpus\fleurs-id\manifest.jsonl `
  --engine-json '{"name":"qwen3-0.6b-q8-cpu4","kind":"transcribe_cpp","model":"qwen3-asr-0.6b/Qwen3-ASR-0.6B-Q8_0.gguf","backend":"cpu","threads":4}'

# 4. Seluruh matriks (configs/s4_matrix.json), lalu laporan
.venv\Scripts\python.exe scripts\run_matrix.py --manifest ..\..\.data\corpus\fleurs-id\manifest.jsonl
.venv\Scripts\python.exe -m recap_eval.report --out ..\..\docs\spikes\S4-hasil-fleurs.md
```

Korpus meeting nyata: ikuti `docs/spikes/S0-panduan-korpus.md`, lalu jalankan langkah 3/4 dengan manifest `id-meeting`.

## Metrik

| Metrik | Arti | Modul |
|---|---|---|
| WER / CER | Word/character error rate setelah normalisasi Indonesia (angka ke kata, tanda hubung, tanda baca, kata pengisi, anotasi `[...]` dibuang) | `metrics.py`, `normalize.py` |
| CS-WER | Error pada token yang di gold ditandai `{bahasa Inggris}` | `metrics.py` |
| Halusinasi | Kata per menit pada item set `silence` (gold kosong) | `metrics.py` |
| Kecepatan / RTF | Waktu inferensi murni dibagi durasi audio (load model dipisah) | `bench.py` |
| Puncak RAM | Peak working set proses benchmark (satu konfigurasi per proses) | `bench.py` |
| DER | Diarization error rate berbasis frame dengan Hungarian mapping dan collar (untuk S7) | `der.py` |

## Catatan kejujuran data

- `cpu4` (4 thread di i7-13620H) hanya **simulasi kasar** tier hemat. Angkanya optimistis sampai diuji di laptop 8 GB nyata.
- FLEURS adalah ucapan terbaca yang bersih. Angkanya bukan prediksi kualitas meeting.
- Bila gold dibuat dengan mengoreksi hasil sebuah model, catat di manifest (`gold_method`), karena model itu diuntungkan.
