import base64
import binascii
import os
import secrets
from pathlib import Path

from fastapi import HTTPException
import httpx

UPLOADS_ROOT = Path(__file__).resolve().parent / "static" / "uploads"
MAX_IMAGE_BYTES = 2 * 1024 * 1024
_MIME_BY_EXT = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}


def _supabase_storage_cfg() -> tuple[str, str, str]:
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "shika-uploads").strip() or "shika-uploads"
    return url, key, bucket


def is_allowed_image_url(url: str) -> bool:
    cleaned = url.strip()
    if cleaned.startswith("/") and not cleaned.startswith("//"):
        return True
    sb_url, _, bucket = _supabase_storage_cfg()
    if sb_url:
        public_prefix = f"{sb_url}/storage/v1/object/public/{bucket}/"
        if cleaned.startswith(public_prefix):
            return True
    return False


def detect_image_ext(raw: bytes) -> str | None:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    return None


def save_local_image(image_data: str, folder: str, prefix: str) -> str:
    raw_str = image_data.strip()
    if "," not in raw_str or not raw_str.lower().startswith("data:image/"):
        raise HTTPException(status_code=422, detail="Invalid image data URI")
    header, b64_payload = raw_str.split(",", 1)
    if ";base64" not in header.lower():
        raise HTTPException(status_code=422, detail="Image must be base64-encoded")
    try:
        raw_bytes = base64.b64decode(b64_payload, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="Corrupt base64 image payload")

    if len(raw_bytes) == 0 or len(raw_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=422, detail="Image must be under 2 MB")
    ext = detect_image_ext(raw_bytes)
    if not ext:
        raise HTTPException(status_code=422, detail="Only PNG, JPEG, and WebP images are supported")

    filename = f"{prefix}_{secrets.token_hex(6)}.{ext}"
    sb_url, sb_key, bucket = _supabase_storage_cfg()
    if sb_url and sb_key:
        object_path = f"{folder}/{filename}"
        try:
            res = httpx.post(
                f"{sb_url}/storage/v1/object/{bucket}/{object_path}",
                content=raw_bytes,
                headers={
                    "Authorization": f"Bearer {sb_key}",
                    "apikey": sb_key,
                    "Content-Type": _MIME_BY_EXT[ext],
                    "x-upsert": "true",
                },
                timeout=15.0,
            )
            res.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(status_code=502, detail="Failed to upload image to Supabase Storage")
        return f"{sb_url}/storage/v1/object/public/{bucket}/{object_path}"

    target_dir = UPLOADS_ROOT / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / filename).write_bytes(raw_bytes)
    return f"/static/uploads/{folder}/{filename}"


def remove_local_upload(image_url: str | None, folder: str) -> None:
    if not image_url:
        return
    sb_url, sb_key, bucket = _supabase_storage_cfg()
    if sb_url and sb_key:
        sb_prefix = f"{sb_url}/storage/v1/object/public/{bucket}/{folder}/"
        if image_url.startswith(sb_prefix):
            filename = Path(image_url[len(sb_prefix) :]).name
            if filename and "/" not in filename and "\\" not in filename:
                try:
                    httpx.delete(
                        f"{sb_url}/storage/v1/object/{bucket}/{folder}/{filename}",
                        headers={"Authorization": f"Bearer {sb_key}", "apikey": sb_key},
                        timeout=10.0,
                    )
                except httpx.HTTPError:
                    pass
            return

    url_prefix = f"/static/uploads/{folder}/"
    if not image_url.startswith(url_prefix):
        return
    filename = Path(image_url[len(url_prefix) :]).name
    if not filename or "/" in filename or "\\" in filename:
        return
    target = UPLOADS_ROOT / folder / filename
    try:
        if target.is_file():
            target.unlink()
    except OSError:
        pass
