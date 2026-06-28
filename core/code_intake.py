"""Safely turn an uploaded code file or .zip into a bounded text blob.

Security notes (this code ingests untrusted uploads):
- ZIPs are read entry-by-entry IN MEMORY — nothing is written to disk, so there
  is no zip-slip path-traversal risk.
- Per-file and total-size caps prevent zip-bomb / memory exhaustion.
- Only text-like source extensions are read; binaries are skipped.
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

ALLOWED_EXT = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".rb", ".php",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".kt", ".swift", ".scala", ".m",
    ".html", ".htm", ".css", ".scss", ".sql", ".sh", ".bash", ".ps1", ".json",
    ".yaml", ".yml", ".toml", ".ini", ".env", ".cfg", ".xml", ".vue", ".svelte",
    ".md", ".txt", ".dockerfile",
}
MAX_FILES = 60
MAX_FILE_BYTES = 256 * 1024          # 256 KB per file
MAX_TOTAL_CHARS = 180_000            # bounded prompt size
MAX_ZIP_UNCOMPRESSED = 25 * 1024 * 1024  # 25 MB zip-bomb guard


@dataclass
class Intake:
    files: list[tuple[str, str]]   # (path, content)
    skipped: int
    truncated: bool


def _is_text_name(name: str) -> bool:
    lower = name.lower()
    if lower.endswith("dockerfile") or lower.endswith("makefile"):
        return True
    dot = lower.rfind(".")
    return dot != -1 and lower[dot:] in ALLOWED_EXT


def from_attachment(filename: str, data: bytes) -> Intake:
    """Build an Intake from one uploaded file (a .zip or a single source file)."""
    if filename.lower().endswith(".zip"):
        return _from_zip(data)
    return _from_single(filename, data)


def _from_single(filename: str, data: bytes) -> Intake:
    if not _is_text_name(filename):
        return Intake(files=[], skipped=1, truncated=False)
    text = data[:MAX_FILE_BYTES].decode("utf-8", errors="replace")
    return Intake(files=[(filename, text)], skipped=0, truncated=len(data) > MAX_FILE_BYTES)


def _from_zip(data: bytes) -> Intake:
    files: list[tuple[str, str]] = []
    skipped = 0
    truncated = False
    total_uncompressed = 0
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return Intake(files=[], skipped=1, truncated=False)

    for info in zf.infolist():
        if info.is_dir():
            continue
        if len(files) >= MAX_FILES:
            truncated = True
            break
        total_uncompressed += info.file_size
        if total_uncompressed > MAX_ZIP_UNCOMPRESSED:
            truncated = True
            break
        if not _is_text_name(info.filename) or info.file_size > MAX_FILE_BYTES:
            skipped += 1
            continue
        try:
            with zf.open(info) as fh:
                raw = fh.read(MAX_FILE_BYTES)
            files.append((info.filename, raw.decode("utf-8", errors="replace")))
        except Exception:  # noqa: BLE001
            skipped += 1
    return Intake(files=files, skipped=skipped, truncated=truncated)


def build_blob(intake: Intake) -> str:
    """Concatenate files into one bounded, header-delimited blob for the model."""
    chunks: list[str] = []
    used = 0
    for path, content in intake.files:
        header = f"\n===== FILE: {path} =====\n"
        budget = MAX_TOTAL_CHARS - used - len(header)
        if budget <= 0:
            break
        body = content[:budget]
        chunks.append(header + body)
        used += len(header) + len(body)
    return "".join(chunks)
