from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path

SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
FULLWIDTH_INVALID = str.maketrans("：／＼｜？＊＜＞＂", '--\\--*<>"')


def is_supported(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS


def sanitize_filename_stem(value: str, fallback: str = "未命名文件") -> str:
    value = value.translate(FULLWIDTH_INVALID)
    value = INVALID_CHARS.sub("-", value)
    value = re.sub(r"\s+", " ", value).strip(" ._-")
    value = re.sub(r"[-_]{2,}", "_", value)
    if not value:
        value = fallback
    if value.upper() in WINDOWS_RESERVED:
        value = f"{value}_文件"
    return value[:120].rstrip(" .")


def collision_safe_path(path: Path, source: Path | None = None) -> Path:
    if not path.exists() or (source is not None and _same_path(path, source)):
        return path
    for number in range(2, 10_000):
        candidate = path.with_name(f"{path.stem}_{number}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"無法為 {path.name} 找到可用檔名")


def rename_safely(source: Path, proposed_name: str) -> Path:
    source = source.resolve()
    if not source.exists():
        raise FileNotFoundError(f"找不到檔案：{source}")
    extension = source.suffix.lower()
    stem = sanitize_filename_stem(Path(proposed_name).stem)
    destination = collision_safe_path(source.with_name(f"{stem}{extension}"), source)
    if _same_path(source, destination):
        return source
    os.replace(source, destination)
    return destination


def restore_safely(current: Path, original: Path) -> Path:
    current = current.resolve()
    if not current.exists():
        raise FileNotFoundError(f"找不到目前檔案：{current}")
    destination = collision_safe_path(original.resolve(), current)
    os.replace(current, destination)
    return destination


def source_fingerprint(path: Path) -> str:
    stat = path.stat()
    digest = hashlib.sha256()
    digest.update(str(stat.st_size).encode("ascii"))
    digest.update(str(stat.st_mtime_ns).encode("ascii"))
    with path.open("rb") as handle:
        digest.update(handle.read(64 * 1024))
    return digest.hexdigest()


def wait_until_stable(
    path: Path, *, settle_seconds: float = 2.0, timeout_seconds: float = 120.0
) -> bool:
    """Wait until size and mtime remain unchanged, avoiding half-written scanner files."""
    deadline = time.monotonic() + timeout_seconds
    last_signature: tuple[int, int] | None = None
    stable_since: float | None = None
    while time.monotonic() < deadline:
        try:
            stat = path.stat()
            signature = (stat.st_size, stat.st_mtime_ns)
            if signature == last_signature and stat.st_size > 0:
                stable_since = stable_since or time.monotonic()
                if time.monotonic() - stable_since >= settle_seconds:
                    return True
            else:
                last_signature = signature
                stable_since = None
        except (FileNotFoundError, PermissionError, OSError):
            stable_since = None
        time.sleep(min(0.5, settle_seconds / 2))
    return False


def _same_path(first: Path, second: Path) -> bool:
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(
        os.path.abspath(second)
    )
