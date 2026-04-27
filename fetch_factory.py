from __future__ import annotations

import os
import re
import sys
import urllib.request
import zipfile
from pathlib import Path


INDEX_URL = "https://developers.google.com/android/images"
TOS_COOKIE = "devsite_wall_acks=nexus-image-tos"
CACHE_ROOT = Path("/tmp/gms-fetch")
TOOLS_DIR = CACHE_ROOT / "tools"
APKTOOL_LATEST_API = "https://api.github.com/repos/iBotPeaches/Apktool/releases/latest"
BASE_BUILD_RE = re.compile(r"\.\d{6}\.\d{3}-factory", re.IGNORECASE)
DEFAULT_DEVICE = "caiman"


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (gms-fetch)",
            "Cookie": TOS_COOKIE,
        },
    )
    with urllib.request.urlopen(req) as resp:
        return resp.read()


def _http_head_size(url: str) -> int:
    req = urllib.request.Request(
        url,
        method="HEAD",
        headers={
            "User-Agent": "Mozilla/5.0 (gms-fetch)",
            "Cookie": TOS_COOKIE,
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return int(resp.headers.get("Content-Length", "0"))
    except Exception as e:
        print(f"[fetch] HEAD failed ({e}); proceeding without size check")
        return 0


def _http_download(url: str, dest: Path, resume_from: int = 0) -> None:
    headers = {
        "User-Agent": "Mozilla/5.0 (gms-fetch)",
        "Cookie": TOS_COOKIE,
    }
    mode = "wb"
    done = 0
    if resume_from > 0:
        headers["Range"] = f"bytes={resume_from}-"
        mode = "ab"
        done = resume_from
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as src, open(dest, mode) as dst:
        remaining = int(src.headers.get("Content-Length", "0"))
        total = remaining + resume_from
        while True:
            buf = src.read(1024 * 1024)
            if not buf:
                break
            dst.write(buf)
            done += len(buf)
            if total:
                pct = done * 100 // total
                sys.stdout.write(
                    f"\r[fetch] {done // (1024 * 1024)}/{total // (1024 * 1024)} MiB ({pct}%)"
                )
                sys.stdout.flush()
        sys.stdout.write("\n")


def _resolve_latest(device: str, release: str, html: str) -> tuple[str, str]:
    dev = re.escape(device)
    rel = re.escape(release)
    url_re = re.compile(
        rf"https://dl\.google\.com/dl/android/aosp/{dev}-{rel}\."
        rf"[^\"\s]+-factory-[a-f0-9]+\.zip",
        re.IGNORECASE,
    )
    bid_re = re.compile(rf"{dev}-({rel}\.[^-]+)-factory", re.IGNORECASE)
    all_urls = sorted(set(url_re.findall(html)))
    if not all_urls:
        raise SystemExit(f"[fetch] No {release} factory image found for {device}")
    base_urls = [u for u in all_urls if BASE_BUILD_RE.search(u)]
    pool = base_urls or all_urls
    pool.sort(key=lambda u: bid_re.search(u).group(1))
    latest = pool[-1]
    build_id = bid_re.search(latest).group(1).lower()
    return latest, build_id


def _find_inner(device: str, extract_dir: Path) -> Path | None:
    if not extract_dir.exists():
        return None
    prefix = f"{device.lower()}-"
    for p in extract_dir.iterdir():
        if p.is_dir() and p.name.lower().startswith(prefix):
            return p
    return None


PARTITIONS = ("system", "product", "system_ext")


def _inner_intact(inner: Path) -> bool:
    if not (inner / "flash-all.sh").exists():
        return False
    if any((inner / f"{p}.img").exists() for p in PARTITIONS):
        return True
    if any(inner.glob("image-*.zip")):
        return True
    for p in PARTITIONS:
        d = inner / p
        if d.is_dir() and any(d.iterdir()):
            return True
    return False


def fetch_apktool_jar() -> str:
    import json

    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    jar_path = TOOLS_DIR / "apktool.jar"
    if jar_path.exists() and jar_path.stat().st_size > 1_000_000:
        print(f"[fetch] apktool jar cached: {jar_path}")
        return str(jar_path)

    print(f"[fetch] resolving latest apktool from {APKTOOL_LATEST_API}")
    req = urllib.request.Request(
        APKTOOL_LATEST_API,
        headers={"User-Agent": "Mozilla/5.0 (gms-fetch)", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req) as resp:
        meta = json.loads(resp.read().decode("utf-8"))
    asset_url = next(
        (a["browser_download_url"] for a in meta.get("assets", []) if a["name"].startswith("apktool_") and a["name"].endswith(".jar")),
        None,
    )
    if not asset_url:
        raise SystemExit("[fetch] no apktool jar in latest release assets")
    print(f"[fetch] downloading apktool {meta.get('tag_name', '?')} -> {jar_path}")
    _http_download(asset_url, jar_path)
    return str(jar_path)


def _purge_empty_partition_stubs(inner: Path) -> None:
    for name in ("system", "system_ext", "product", "vendor", "odm"):
        d = inner / name
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
            print(f"[fetch] purged empty partition stub: {d}")


def fetch_latest_factory(device: str = DEFAULT_DEVICE, release: str = "bp4a") -> str:
    print(f"[fetch] index: {INDEX_URL}")
    html = _http_get(INDEX_URL).decode("utf-8", errors="replace")
    latest, build_id = _resolve_latest(device, release, html)
    print(f"[fetch] latest: {build_id}")
    print(f"[fetch] url:    {latest}")

    cache = CACHE_ROOT / build_id
    cache.mkdir(parents=True, exist_ok=True)
    extract_dir = cache / "extracted"
    zip_path = cache / "factory.zip"

    inner = _find_inner(device, extract_dir)
    if inner is not None and _inner_intact(inner):
        print(f"[fetch] reusing extracted cache: {inner}")
        _purge_empty_partition_stubs(inner)
        return str(inner)

    expected_size = _http_head_size(latest)
    have = zip_path.stat().st_size if zip_path.exists() else 0

    if have and expected_size and have == expected_size:
        size_mib = have // (1024 * 1024)
        print(f"[fetch] zip cache hit: {zip_path} ({size_mib} MiB)")
    elif have and expected_size and have < expected_size:
        print(
            f"[fetch] resuming partial: "
            f"{have // (1024 * 1024)}/{expected_size // (1024 * 1024)} MiB"
        )
        _http_download(latest, zip_path, resume_from=have)
    else:
        if have and expected_size and have > expected_size:
            print(f"[fetch] stale zip ({have} > {expected_size}); re-downloading")
            zip_path.unlink()
        print(f"[fetch] downloading -> {zip_path}")
        _http_download(latest, zip_path)

    if inner is None or not _inner_intact(inner):
        print(f"[fetch] unpacking -> {extract_dir}")
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(extract_dir)
        inner = _find_inner(device, extract_dir)
    if inner is None:
        raise SystemExit(f"[fetch] no {device}-* dir inside {extract_dir}")
    print(f"[fetch] dump root: {inner}")
    return str(inner)


if __name__ == "__main__":
    device = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("FETCH_DEVICE", DEFAULT_DEVICE)
    release = sys.argv[2] if len(sys.argv) > 2 else "bp4a"
    print(fetch_latest_factory(device, release))
