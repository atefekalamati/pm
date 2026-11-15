"""Chat images: stored as BLOBs (docs/DATABASE.md section 5). The browser already shrinks them before upload."""

import sqlite3

from fastapi import HTTPException

from app.board import bad, is_member, not_found
from app.db import new_id, now_iso, tx

MAX_IMAGE_BYTES = 2 * 1024 * 1024
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")


def store_image(conn: sqlite3.Connection, board_id: str, uploader_id: str, file_name: str, mime_type: str, data: bytes) -> dict:
    """Saves an upload that has no message yet. Sending a message attaches it; unattached ones are purged after 24 h."""
    if mime_type not in IMAGE_TYPES:
        raise bad("The image must be a JPEG, PNG or WebP file")
    if not data:
        raise bad("The image is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="The image is larger than 2 MB")
    image_id = new_id()
    with tx(conn):
        conn.execute(
            "INSERT INTO images (id, board_id, uploader_id, file_name, mime_type, size_bytes, data, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (image_id, board_id, uploader_id, file_name, mime_type, len(data), data, now_iso()),
        )
    return {"id": image_id, "file": file_name, "src": f"/api/images/{image_id}"}


def read_image(conn: sqlite3.Connection, user_id: str, image_id: str) -> tuple[bytes, str]:
    """Only members of the image's board can read it. Sample placeholders have no bytes."""
    row = conn.execute("SELECT board_id, mime_type, data FROM images WHERE id = ?", (image_id,)).fetchone()
    if not row or row["data"] is None or not is_member(conn, row["board_id"], user_id):
        raise not_found("Image")
    return row["data"], row["mime_type"]
