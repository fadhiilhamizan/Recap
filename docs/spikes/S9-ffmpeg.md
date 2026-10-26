# S9. Hasil Decode File Import dengan ffmpeg LGPL

Dijalankan: 2026-10-10 11:59 · ffmpeg version n9.0.2-24-gfd5d616c29-20261009 Copyright (c) 2000-2026 the FFmpeg developers
Build: BtbN/FFmpeg-Builds `ffmpeg-n9.0-latest-win64-lgpl-shared-9.0` (tanpa `--enable-gpl`/`--enable-nonfree`; berlisensi LGPL v3 karena `--enable-version3` untuk opencore-amr).

Perintah decode (sama dengan rencana `recap-app`): `ffmpeg -i <file> -map 0:a:0 -vn -ac 1 -ar 16000 -c:a pcm_s16le out.wav`.
Lulus untuk file valid: decode sukses, durasi selisih 0,5 detik atau kurang, dan **WER STT (Qwen3-ASR-0.6B) hasil decode tidak lebih dari 5 poin di atas WER audio sumber** (21.0%; AMR 8 kHz diberi toleransi 10 poin). File terpotong lulus bila bagian yang tersisa terbaca utuh. File bukan media lulus bila ditolak dengan error.
Kolom kemiripan (korelasi sampel) hanya informasi: rendah untuk codec lossy bitrate rendah walau isinya terbaca.

| Jenis | File | Valid | Codec audio | Durasi probe (s) | Durasi decode (s) | Harapan (s) | WER STT (%) | Kemiripan | Waktu decode (s) | Hasil | Error |
|---|---|---|---|---|---|---|---|---|---|---|---|
| mp3 | `rapat.mp3` | ya | mp3 | 67.9 | 67.9 | 67.9 | 18.5 | 1.0 | 0.12 | **Lulus** |  |
| m4a-aac | `rapat.m4a` | ya | aac | 67.9 | 67.9 | 67.9 | 16.0 | 1.0 | 0.1 | **Lulus** |  |
| wav-24bit-48k-stereo | `rapat-24bit.wav` | ya | pcm_s24le | 67.9 | 67.9 | 67.9 | 18.5 | 1.0 | 0.08 | **Lulus** |  |
| flac | `rapat.flac` | ya | flac | 67.9 | 67.9 | 67.9 | 21.0 | 1.0 | 0.06 | **Lulus** |  |
| ogg-vorbis | `rapat.ogg` | ya | vorbis | 67.9 | 67.9 | 67.9 | 17.6 | 0.998 | 0.08 | **Lulus** |  |
| opus-whatsapp | `PTT-20261010-WA0001.opus` | ya | opus | 67.9 | 67.9 | 67.9 | 18.5 | 0.778 | 0.13 | **Lulus** |  |
| mp4-h264-aac | `zoom-rekaman.mp4` | ya | aac | 67.9 | 67.9 | 67.9 | 16.0 | 0.999 | 0.1 | **Lulus** |  |
| mkv-vp9-opus | `meet-rekaman.mkv` | ya | opus | 68.7 | 67.9 | 67.9 | 18.5 | 0.999 | 0.17 | **Lulus** |  |
| webm-vp8-vorbis | `rekaman.webm` | ya | vorbis | 67.9 | 67.9 | 67.9 | 17.6 | 0.997 | 0.08 | **Lulus** |  |
| mov-iphone-aac | `IMG_0042.mov` | ya | aac | 67.9 | 67.9 | 67.9 | 19.3 | 1.0 | 0.12 | **Lulus** |  |
| wma | `rapat.wma` | ya | wmav2 | 67.9 | 67.8 | 67.9 | 15.1 | 0.096 | 0.08 | **Lulus** |  |
| amr-nb | `rekaman.amr` | ya | amr_nb | 70.1 | 67.9 | 67.9 | 16.8 | 0.484 | 0.1 | **Lulus** |  |
| 3jam-m4a | `seminar-3jam.m4a` | ya | aac | 12214.8 | 12214.8 | 12214.8 | None | None | 3.55 | **Lulus** |  |
| mp3-terpotong | `terpotong.mp3` | ya | mp3 | 22.6 | 22.6 | 22.6 | None | None | 0.06 | **Lulus** |  |
| sampah-ekstensi-mp3 | `bukan-audio.mp3` | tidak | mp3 | 100.0 | None | 67.9 | None | None | 0.06 | **Lulus** |  -1145393733 (Error number -1145393733 occurred)
[aist#0:0/mp3 @ 0000017997647840] [dec:mp3float @ 0000017997657740] Ter |
| video-tanpa-audio | `video-tanpa-audio.mp4` | tidak |  | 10.0 | None | 67.9 | None | None | 0.03 | **Lulus** |  for option 'map': Invalid argument
Error parsing options for output file C:\Users\fadhi\Documents\Project\Recap\.data\s |

**Ringkasan:** 14/14 file valid lulus; 2/2 file tidak valid ditolak dengan benar.
