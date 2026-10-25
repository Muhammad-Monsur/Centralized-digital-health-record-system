"""Safe storage for uploaded medical documents.

* Allowed types are checked by *content signature* (magic bytes), not by the
  extension or the browser-supplied Content-Type, which are both attacker-controlled.
* Size is enforced while streaming (we never read an unbounded body into memory).
* The file on disk gets a random name; the original name is sanitised and only
  used for display / the download filename.
* Files live outside the static folder, so they can only be fetched through an
  authorised endpoint.
"""
from __future__ import annotations

import os
import re
import secrets
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.config import settings

# extension -> (mime, list of acceptable leading signatures)
ALLOWED: dict[str, tuple[str, list[bytes]]] = {
    "pdf": ("application/pdf", [b"%PDF-"]),
    "png": ("image/png", [b"\x89PNG\r\n\x1a\n"]),
    "jpg": ("image/jpeg", [b"\xff\xd8\xff"]),
    "jpeg": ("image/jpeg", [b"\xff\xd8\xff"]),
    "webp": ("image/webp", [b"RIFF"]),  # + "WEBP" at offset 8, checked below
}
ACCEPT_ATTR = ".pdf,.png,.jpg,.jpeg,.webp,application/pdf,image/png,image/jpeg,image/webp"
_CHUNK = 64 * 1024


class FileError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class StoredFile:
    stored_name: str
    original_name: str
    mime: str
    size: int


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Strip paths, control chars and anything outside a conservative set."""
    name = unicodedata.normalize("NFKC", name or "")
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = re.sub(r"[^\w.\- ()]+", "_", name, flags=re.UNICODE).strip(" ._")
    name = re.sub(r"_+", "_", name)
    if not name:
        name = "document"
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    stem = stem[: max_len - len(ext) - 1]
    return f"{stem}.{ext.lower()}" if ext else stem


def _detect(head: bytes) -> tuple[str, str] | None:
    for ext, (mime, sigs) in ALLOWED.items():
        if any(head.startswith(s) for s in sigs):
            if ext == "webp" and head[8:12] != b"WEBP":
                continue
            return ext, mime
    return None


async def save_upload(upload: UploadFile) -> StoredFile:
    original = sanitize_filename(upload.filename or "document")
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in ALLOWED:
        raise FileError("Upload a PDF, PNG, JPG or WebP file.")

    limit = settings.max_upload_mb * 1024 * 1024
    head = await upload.read(16)
    detected = _detect(head)
    if detected is None:
        raise FileError("That file's contents don't match a PDF or image. Choose another file.")
    det_ext, mime = detected
    if {det_ext, ext} - {"jpg", "jpeg"} and det_ext != ext:
        raise FileError(f"The file looks like a {det_ext.upper()} but is named .{ext}. Rename it or choose another file.")

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{secrets.token_hex(16)}.{det_ext}"
    target = settings.upload_dir / stored
    size = len(head)
    try:
        # O_EXCL: never overwrite; 0o640: not world-readable.
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        with os.fdopen(fd, "wb") as out:
            out.write(head)
            while chunk := await upload.read(_CHUNK):
                size += len(chunk)
                if size > limit:
                    raise FileError(f"The file is larger than {settings.max_upload_mb} MB.")
                out.write(chunk)
    except FileError:
        target.unlink(missing_ok=True)
        raise
    if size < 32:
        target.unlink(missing_ok=True)
        raise FileError("The file is empty or damaged.")
    return StoredFile(stored_name=stored, original_name=original, mime=mime, size=size)


def resolve(stored_name: str) -> Path:
    """Map a stored name to a path, refusing anything that escapes the upload dir."""
    if not re.fullmatch(r"[0-9a-f]{32}\.(pdf|png|jpg|jpeg|webp)", stored_name or ""):
        raise FileError("File not found.")
    path = (settings.upload_dir / stored_name).resolve()
    if path.parent != settings.upload_dir.resolve() or not path.is_file():
        raise FileError("File not found.")
    return path


def delete_quietly(stored_name: str | None) -> None:
    if stored_name:
        try:
            resolve(stored_name).unlink(missing_ok=True)
        except FileError:
            pass


def human_size(n: int | None) -> str:
    if not n:
        return "—"
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} GB"
