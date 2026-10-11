"""Local photo attachments. Files are stored on disk; the model never sees the image."""

import re
import sqlite3
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from . import config, db

MAX_PHOTO_BYTES = 8 * 1024 * 1024
_PHOTO_NAME = re.compile(r"^[0-9a-f]{32}\.(jpg|png)$")
_JPEG = b"\xff\xd8\xff"
_PNG = b"\x89PNG\r\n\x1a\n"
CAPTION_NOTE = "from the technician's caption, not from visual analysis of the photo"


def photo_dir() -> Path:
    return config.PHOTO_DIR


def photo_path(name_or_path: str) -> Path:
    """Resolve a client-supplied photo name to a file inside the photo folder, or raise ValueError."""
    name = Path(name_or_path).name
    if not _PHOTO_NAME.match(name):
        raise ValueError("not a stored photo")
    path = (photo_dir() / name).resolve()
    if path.parent != photo_dir().resolve():
        raise ValueError("photo is outside the photo folder")
    return path


def _png_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or not data.startswith(_PNG) or data[12:16] != b"IHDR":
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width < 1 or height < 1:
        return None
    return width, height


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(_JPEG) or len(data) < 4:
        return None
    i = 2
    while i + 8 < len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xD9:
            return None
        if marker == 0xD8 or marker == 0x01 or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if i + 3 >= len(data):
            return None
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        if length < 2:
            return None
        if marker in (0xC0, 0xC1, 0xC2) and i + 8 < len(data):
            height = int.from_bytes(data[i + 5 : i + 7], "big")
            width = int.from_bytes(data[i + 7 : i + 9], "big")
            if width < 1 or height < 1:
                return None
            return width, height
        i += 2 + length
    return None


def inspect_image(data: bytes) -> tuple[str, tuple[int, int]]:
    """Return ('jpg'|'png', (width, height)) or raise ValueError if the bytes are not a JPEG/PNG."""
    png = _png_size(data)
    if png:
        return "png", png
    jpeg = _jpeg_size(data)
    if jpeg:
        return "jpg", jpeg
    raise ValueError("The file is not a JPEG or PNG image.")


def save_upload(upload: UploadFile) -> str:
    """Validate and store an upload. Returns the stored file name (stable id)."""
    data = upload.file.read(MAX_PHOTO_BYTES + 1)
    if not data:
        raise HTTPException(422, "The photo is empty.")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "The photo is too large (limit 8 MB).")
    try:
        kind, _size = inspect_image(data)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    folder = photo_dir()
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{kind}"
    path = folder / name
    path.write_bytes(data)
    return name


def delete_file(name: str) -> None:
    try:
        photo_path(name).unlink(missing_ok=True)
    except ValueError:
        return


def referenced_photo_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT DISTINCT photo_path FROM sources WHERE photo_path IS NOT NULL").fetchall()
    return {Path(r[0]).name for r in rows}


def source_owns_photo(conn: sqlite3.Connection, job_id: int, name: str) -> bool:
    return any(Path(s.photo_path).name == name for s in db.list_sources(conn, job_id) if s.photo_path)
