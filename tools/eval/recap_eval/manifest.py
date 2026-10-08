"""Format manifest korpus (JSON Lines).

Satu baris = satu item:
{
  "id": "fleurs-id-0001",
  "set": "fleurs-id" | "id-meeting" | "id-en" | "en-meeting" | "hard" | "silence",
  "audio": "audio/xxx.wav",          # relatif terhadap folder manifest
  "ref": "teks gold" | null,          # atau "ref_file": "gold/xxx.txt"
  "language": "id" | "en",            # bahasa utama (untuk mode bahasa dikunci)
  "kind": "utterance" | "longform",   # longform = rekaman panjang yang harus disegmentasi VAD
  "consent": "public-cc-by-4.0" | "written-all-participants" | ...,
  "notes": "..."
}
Audio korpus pribadi tidak pernah di-commit; hanya manifest dan hash.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Item:
    id: str
    set: str
    audio: Path
    ref: str | None
    language: str
    kind: str
    raw: dict


def load_manifest(path: str | Path) -> list[Item]:
    path = Path(path)
    base = path.parent
    items: list[Item] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            d = json.loads(line)
            ref = d.get("ref")
            if ref is None and d.get("ref_file"):
                ref = (base / d["ref_file"]).read_text(encoding="utf-8")
            for key in ("id", "set", "audio"):
                if key not in d:
                    raise ValueError(f"{path}:{line_no}: field '{key}' wajib")
            items.append(
                Item(
                    id=d["id"],
                    set=d["set"],
                    audio=base / d["audio"],
                    ref=ref,
                    language=d.get("language", "id"),
                    kind=d.get("kind", "utterance"),
                    raw=d,
                )
            )
    return items
