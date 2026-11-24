from collections.abc import Generator
from psycopg2.extras import RealDictCursor
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import DATABASE_URL, IS_VERCEL

_is_supabase = ("supabase.co" in DATABASE_URL) or ("supabase.com" in DATABASE_URL)
_use_null_pool = IS_VERCEL or ("pooler.supabase.com" in DATABASE_URL) or (":6543/" in DATABASE_URL)
_connect_args = {"sslmode": "require"} if (_is_supabase and "sslmode=" not in DATABASE_URL) else {}

if _use_null_pool:
    engine = create_engine(
        DATABASE_URL,
        poolclass=NullPool,
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
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_raw_db() -> Generator:
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
