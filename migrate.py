"""Apply SQL migrations and/or migrate existing local images to a Supabase Storage bucket.

Usage:
    # 1. Push schema + seed data + create admin user + migrate existing local images to Supabase Storage:
    python migrate.py --admin-email admin@shika.coffee --admin-password "YourStrongPassword123" --migrate-images

    # 2. Only migrate existing local images (products, raw_materials, users) to Supabase Storage:
    python migrate.py --migrate-images-only
"""

from __future__ import annotations

import argparse
import mimetypes
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import psycopg2

from app.config import load_dotenv_if_present, normalize_database_url
from app.security import hash_password

REPO_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = (REPO_ROOT / "app" / "static").resolve()
_IMAGE_TARGETS = (
    ("products", "image_url", "products"),
    ("raw_materials", "image_url", "roastery"),
    ("users", "avatar_url", "avatars"),
)


def _raw_pg_dsn() -> str:
    load_dotenv_if_present()
    dsn = (os.getenv("DIRECT_URL") or os.getenv("DATABASE_URL") or "").strip()
    if not dsn:
        raise SystemExit("Set DIRECT_URL or DATABASE_URL in .env before running migrate.py")
    dsn = normalize_database_url(dsn)
    if dsn.startswith("postgresql+psycopg2://"):
        dsn = "postgresql://" + dsn[len("postgresql+psycopg2://") :]
    if ("supabase.co" in dsn or "supabase.com" in dsn) and "sslmode=" not in dsn:
        dsn += ("&" if "?" in dsn else "?") + "sslmode=require"
    return dsn


def _supabase_bucket_cfg(require_key: bool = True) -> tuple[str, str, str]:
    load_dotenv_if_present()
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "shika-uploads").strip() or "shika-uploads"
    if not url or (require_key and not key):
        needed = "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY" if require_key else "SUPABASE_URL"
        raise SystemExit(f"Set {needed} in .env first.")
    return url, key, bucket


def _resolve_static_file(url_path: str) -> Path | None:
    cleaned = url_path.strip()
    if not cleaned.startswith("/static/"):
        return None
    rel = cleaned[len("/static/") :].lstrip("/")
    candidate = (STATIC_ROOT / rel).resolve()
    try:
        candidate.relative_to(STATIC_ROOT)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _object_path_for(url_path: str, fallback_folder: str) -> str:
    cleaned = url_path.strip()
    if cleaned.startswith("/static/uploads/"):
        return cleaned[len("/static/uploads/") :].lstrip("/")
    if cleaned.startswith("/static/images/"):
        return cleaned[len("/static/images/") :].lstrip("/")
    return f"{fallback_folder}/{Path(cleaned).name}"


def ensure_supabase_bucket(sb_url: str, sb_key: str, bucket: str) -> None:
    res = httpx.post(
        f"{sb_url}/storage/v1/bucket",
        json={"id": bucket, "name": bucket, "public": True},
        headers={
            "Authorization": f"Bearer {sb_key}",
            "apikey": sb_key,
            "Content-Type": "application/json",
        },
        timeout=15.0,
    )
    # 200/201 created, 409 (or 400 with "already exists") means bucket already exists
    if res.status_code in (200, 201, 409):
        return
    if res.status_code == 400 and "already exists" in res.text.lower():
        return
    res.raise_for_status()


def migrate_images_to_supabase(
    conn: Any,
    sb_url: str,
    sb_key: str,
    bucket: str,
    *,
    upload_files: bool = True,
) -> dict[str, int]:
    if upload_files:
        ensure_supabase_bucket(sb_url, sb_key, bucket)
    uploaded_cache: dict[str, str] = {}
    rows_updated = 0
    skipped = 0

    with conn.cursor() as cur:
        for table, column, fallback_folder in _IMAGE_TARGETS:
            cur.execute(
                f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL AND {column} LIKE '/static/%'"
            )
            urls = [row[column] if isinstance(row, dict) else row[0] for row in cur.fetchall()]
            for local_url in urls:
                if local_url in uploaded_cache:
                    public_url = uploaded_cache[local_url]
                else:
                    object_path = _object_path_for(local_url, fallback_folder)
                    if upload_files:
                        local_file = _resolve_static_file(local_url)
                        if not local_file:
                            skipped += 1
                            continue
                        content_type = mimetypes.guess_type(local_file.name)[0] or "application/octet-stream"
                        res = httpx.post(
                            f"{sb_url}/storage/v1/object/{bucket}/{object_path}",
                            content=local_file.read_bytes(),
                            headers={
                                "Authorization": f"Bearer {sb_key}",
                                "apikey": sb_key,
                                "Content-Type": content_type,
                                "x-upsert": "true",
                                "cache-control": "31536000",
                            },
                            timeout=30.0,
                        )
                        res.raise_for_status()
                    public_url = f"{sb_url}/storage/v1/object/public/{bucket}/{object_path}"
                    uploaded_cache[local_url] = public_url

                cur.execute(f"UPDATE {table} SET {column} = %s WHERE {column} = %s", (public_url, local_url))
                rows_updated += cur.rowcount

    conn.commit()
    return {"files_uploaded": len(uploaded_cache) if upload_files else 0, "rows_updated": rows_updated, "skipped": skipped}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Shika Coffee SQL migrations and/or Supabase image migration.")
    parser.add_argument("--admin-email", default=os.getenv("SEED_ADMIN_EMAIL", "").strip())
    parser.add_argument("--admin-password", default=os.getenv("SEED_ADMIN_PASSWORD", "").strip())
    parser.add_argument("--admin-name", default=os.getenv("SEED_ADMIN_NAME", "Shika Admin").strip())
    parser.add_argument("--admin-username", default=os.getenv("SEED_ADMIN_USERNAME", "admin").strip())
    parser.add_argument("--migrate-images", action="store_true", help="Upload local /static/ DB images to Supabase Storage and update DB URLs.")
    parser.add_argument("--migrate-images-only", action="store_true", help="Skip SQL files and only upload & rewrite local DB images to Supabase Storage.")
    parser.add_argument("--rewrite-image-urls", action="store_true", help="Rewrite DB /static/ image paths to Supabase public bucket URLs without re-uploading files.")
    args = parser.parse_args()

    dsn = _raw_pg_dsn()
    parsed = urlparse(dsn)
    print(f"Connecting to {parsed.hostname}:{parsed.port or 5432}{parsed.path}...")

    migrations_dir = REPO_ROOT / "migrations"
    sql_files = sorted(migrations_dir.glob("*.sql"))

    with psycopg2.connect(dsn) as conn:
        if not args.migrate_images_only:
            with conn.cursor() as cur:
                if args.admin_email and args.admin_password:
                    cur.execute((migrations_dir / "001_schema.sql").read_text(encoding="utf-8"))
                    cur.execute(
                        """
                        INSERT INTO users (email, username, password_hash, full_name, role, is_active)
                        VALUES (%s, %s, %s, %s, 'admin', TRUE)
                        ON CONFLICT (email) DO NOTHING
                        """,
                        (args.admin_email.lower(), args.admin_username, hash_password(args.admin_password), args.admin_name),
                    )
                    print(f"Ensured admin account: {args.admin_email.lower()}")
                for sql_file in sql_files:
                    print(f"Applying {sql_file.name}...")
                    cur.execute(sql_file.read_text(encoding="utf-8"))
            conn.commit()
            print("All SQL migrations applied cleanly.")

        if args.migrate_images or args.migrate_images_only or args.rewrite_image_urls:
            do_upload = bool(args.migrate_images or args.migrate_images_only)
            sb_url, sb_key, bucket = _supabase_bucket_cfg(require_key=do_upload)
            stats = migrate_images_to_supabase(conn, sb_url, sb_key, bucket, upload_files=do_upload)
            print(
                f"Supabase Storage sync complete ({bucket}): "
                f"{stats['files_uploaded']} files uploaded, "
                f"{stats['rows_updated']} DB rows updated, {stats['skipped']} skipped."
            )


if __name__ == "__main__":
    main()
