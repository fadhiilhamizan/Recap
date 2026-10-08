"""Ubah transkrip gold berlabel (``[hh:mm:ss] A: teks``) menjadi teks referensi polos.

  python scripts/gold_to_ref.py .data/corpus/id-meeting/gold/rapat-x.txt [--speaker A]

Menulis ``<nama>.ref.txt`` di folder yang sama. Opsi ``--speaker`` hanya mengambil satu
pembicara (berguna untuk kanal mic = "Saya"). Kurung kurawal (penanda Inggris) dan kurung
siku (non-ucapan) dipertahankan; normalisasi saat penilaian yang menanganinya.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

LINE_RE = re.compile(r"^\s*(?:\[(?P<ts>[\d:.]+)\])?\s*(?:(?P<spk>[A-Za-z0-9_ ]{1,20}):)?\s*(?P<text>.*)$")


def convert(path: Path, speaker: str | None = None) -> Path:
    out_lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        m = LINE_RE.match(raw)
        spk = (m.group("spk") or "").strip()
        if speaker and spk != speaker:
            continue
        out_lines.append(m.group("text").strip())
    out = path.with_name(path.name.removesuffix(".txt") + ".ref.txt")
    out.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("gold", type=Path)
    ap.add_argument("--speaker")
    args = ap.parse_args(argv)
    print(convert(args.gold, args.speaker))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
