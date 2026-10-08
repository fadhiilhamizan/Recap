"""Unduh model dan binary untuk spike S4 ke ``.data/`` dengan verifikasi SHA-256.

  python scripts/download_models.py --dry-run              # tampilkan rencana + ruang disk
  python scripts/download_models.py --groups base,s4       # unduh
  python scripts/download_models.py --only qwen3-asr-0.6b  # satu model

Sumber Hugging Face diverifikasi terhadap SHA-256 LFS dari API Hub. Sumber URL lain
(Silero VAD, whisper.cpp) dicatat SHA-256-nya saat unduh pertama (trust on first use)
di ``.data/models/lock.json``; unduhan berikutnya harus cocok.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / ".data"
MODELS = DATA / "models"
LOCK = MODELS / "lock.json"
CATALOG = Path(__file__).resolve().parents[1] / "models.json"
MARGIN_GB = 3.0


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_lock() -> dict:
    return json.loads(LOCK.read_text(encoding="utf-8")) if LOCK.exists() else {}


def save_lock(lock: dict) -> None:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(json.dumps(lock, indent=2, sort_keys=True), encoding="utf-8")


def target_path(item: dict) -> Path:
    return MODELS / item["name"] / item["file"]


def download_resumable(url: str, dest: Path, *, retries: int = 30, timeout: float = 30.0) -> None:
    """Unduh dengan HTTP Range: tahan putus/macet, melanjutkan dari file ``.part``."""
    import time

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    for attempt in range(1, retries + 1):
        have = part.stat().st_size if part.exists() else 0
        req = urllib.request.Request(url, headers={"User-Agent": "recap-eval/0.1", **({"Range": f"bytes={have}-"} if have else {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if have and resp.status != 206:
                    have = 0  # server tidak mendukung Range: mulai ulang
                total = have + int(resp.headers.get("Content-Length", 0))
                with part.open("ab" if have else "wb") as fh:
                    last = time.monotonic()
                    while True:
                        block = resp.read(1 << 20)
                        if not block:
                            break
                        fh.write(block)
                        have += len(block)
                        if time.monotonic() - last > 30:
                            print(f"    {have / 2**20:,.0f} / {total / 2**20:,.0f} MB", flush=True)
                            last = time.monotonic()
            if total and have >= total:
                part.replace(dest)
                return
        except (OSError, TimeoutError) as exc:  # termasuk socket timeout dan koneksi putus
            print(f"    percobaan {attempt}: {exc}; lanjut dari {have / 2**20:,.0f} MB", flush=True)
            time.sleep(min(30, 2 * attempt))
    raise RuntimeError(f"Gagal mengunduh {url} setelah {retries} percobaan")


def fetch_hf(item: dict, lock: dict) -> None:
    from huggingface_hub import HfApi

    info = HfApi().get_paths_info(item["hf_repo"], [item["file"]], expand=True)[0]
    expected = info.lfs.sha256 if info.lfs else None
    dest = target_path(item)
    if dest.exists() and expected and sha256_of(dest) == expected:
        print(f"  sudah ada dan cocok: {dest.relative_to(ROOT)}")
    else:
        url = f"https://huggingface.co/{item['hf_repo']}/resolve/main/{item['file']}"
        download_resumable(url, dest)
    actual = sha256_of(dest)
    if expected and actual != expected:
        dest.unlink()
        raise RuntimeError(f"SHA-256 tidak cocok untuk {item['file']}: {actual} != {expected}")
    lock[str(dest.relative_to(DATA))] = {"sha256": actual, "source": f"hf://{item['hf_repo']}/{item['file']}",
                                         "verified": "hub-lfs" if expected else "tofu", "license": item.get("license")}


def fetch_url(item: dict, lock: dict) -> None:
    dest = target_path(item)
    dest.parent.mkdir(parents=True, exist_ok=True)
    key = str(dest.relative_to(DATA))
    if not dest.exists():
        print(f"  mengunduh {item['url']}")
        tmp = dest.with_suffix(dest.suffix + ".part")
        with urllib.request.urlopen(item["url"]) as resp, tmp.open("wb") as fh:
            shutil.copyfileobj(resp, fh)
        tmp.replace(dest)
    actual = sha256_of(dest)
    pinned = lock.get(key, {}).get("sha256")
    if pinned and pinned != actual:
        raise RuntimeError(f"SHA-256 berubah untuk {key}: {actual} != {pinned} (pin sebelumnya)")
    lock[key] = {"sha256": actual, "source": item["url"], "verified": "pinned" if pinned else "tofu",
                 "license": item.get("license")}
    if item.get("unzip_to"):
        out = DATA / item["unzip_to"]
        if not (out / "whisper-cli.exe").exists():
            out.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(dest) as zf:
                for member in zf.infolist():
                    if member.is_dir():
                        continue
                    name = Path(member.filename).name  # ratakan folder Release/
                    with zf.open(member) as src, (out / name).open("wb") as dst:
                        shutil.copyfileobj(src, dst)
        print(f"  binary di {out.relative_to(ROOT)}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--groups", default="base,s4")
    ap.add_argument("--only", default="", help="nama model dipisah koma")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))["items"]
    groups = set(args.groups.split(","))
    only = set(filter(None, args.only.split(",")))
    if only:
        items = [i for i in catalog if i["name"] in only]
    else:
        items = [i for i in catalog if i["group"] in groups]

    pending = [i for i in items if not target_path(i).exists()]
    need_gb = sum(i["size_mb"] for i in pending) / 1024
    free_gb = shutil.disk_usage(ROOT).free / 2**30
    print(f"{len(items)} item ({len(pending)} belum ada), perlu sekitar {need_gb:.2f} GB, ruang kosong {free_gb:.1f} GB")
    for i in items:
        state = "ada" if target_path(i).exists() else "unduh"
        print(f"  [{state}] {i['name']:<24} {i['file']:<40} {i['size_mb']:>6} MB  {i.get('license', '')}")
    if args.dry_run:
        return 0
    if free_gb - need_gb < MARGIN_GB:
        print(f"Ruang disk tidak cukup (sisakan minimal {MARGIN_GB} GB). Batal.", file=sys.stderr)
        return 3

    lock = load_lock()
    for i in items:
        print(f"- {i['name']} / {i['file']}")
        (fetch_hf if "hf_repo" in i else fetch_url)(i, lock)
        save_lock(lock)
    print("Selesai.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
