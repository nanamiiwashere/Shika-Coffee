from collections.abc import Generator
import os
import re
from fastapi import HTTPException
from psycopg2.extras import RealDictCursor
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import DATABASE_URL, IS_VERCEL

_CRED_RE = re.compile(r"://[^@\s/]+@")
_is_supabase = ("supabase.co" in DATABASE_URL) or ("supabase.com" in DATABASE_URL)
_force_null_pool = os.getenv("DB_NULL_POOL", "").lower() in {"1", "true", "yes"}
_connect_args: dict[str, object] = {}
if _is_supabase and "sslmode=" not in DATABASE_URL:
    _connect_args["sslmode"] = "require"
if IS_VERCEL or _is_supabase:
    _connect_args.update(
        {
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 3,
        }
    )

engine = None
SessionLocal = None
DB_INIT_ERROR: str | None = None

if DATABASE_URL:
    try:
        if _force_null_pool:
            engine = create_engine(
                DATABASE_URL,
                poolclass=NullPool,
                connect_args=_connect_args,
            )
        elif IS_VERCEL:
            # Fluid Compute reuses the warm Python worker across requests; a small recycled pool
            # eliminates per-request TCP+TLS+SCRAM handshakes while staying safe on Supavisor :6543.
            engine = create_engine(
                DATABASE_URL,
                pool_size=4,
                max_overflow=4,
                pool_recycle=60,
                pool_pre_ping=False,
                connect_args=_connect_args,
            )
        else:
            engine = create_engine(
                DATABASE_URL,
                pool_size=10,
                max_overflow=10,
                pool_pre_ping=True,
                connect_args=_connect_args,
            )
        SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    except Exception as exc:
        if not IS_VERCEL:
            raise
        DB_INIT_ERROR = _CRED_RE.sub("://***:***@", f"{type(exc).__name__}: {exc}")
else:
    DB_INIT_ERROR = "DATABASE_URL is not configured"

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    if SessionLocal is None:
        raise HTTPException(status_code=503, detail=f"Database not configured ({DB_INIT_ERROR or 'missing DATABASE_URL'})")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_raw_db() -> Generator:
    if engine is None:
        raise HTTPException(status_code=503, detail=f"Database not configured ({DB_INIT_ERROR or 'missing DATABASE_URL'})")
    raw_conn = engine.raw_connection()
    driver_conn = raw_conn.driver_connection
    try:
        driver_conn.cursor_factory = RealDictCursor
        yield driver_conn
    finally:
        if not driver_conn.closed:
            driver_conn.cursor_factory = None
            driver_conn.rollback()
        raw_conn.close()
