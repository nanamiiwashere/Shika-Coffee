import os
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

_UNSUPPORTED_LIBPQ_PARAMS = frozenset({"pgbouncer", "connection_limit", "pool_timeout", "schema", "supa"})


def load_dotenv_if_present() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def normalize_database_url(raw_url: str) -> str:
    url = raw_url.strip().strip('"').strip("'")
    if not url:
        return url
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://") :]
    if "://" in url:
        scheme, rest = url.split("://", 1)
        if "@" in rest:
            userinfo, hostpart = rest.rsplit("@", 1)
            if ":" in userinfo:
                user, pw = userinfo.split(":", 1)
                if any(ch in pw for ch in "@:/?#[] "):
                    url = f"{scheme}://{user}:{quote(pw, safe='')}@{hostpart}"
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if parts.query:
        filtered = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in _UNSUPPORTED_LIBPQ_PARAMS]
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(filtered), parts.fragment))
    return url


IS_VERCEL = bool(os.getenv("VERCEL"))
if not IS_VERCEL:
    load_dotenv_if_present()

MISSING_ENV_VARS: list[str] = []

if IS_VERCEL:
    _raw_db_url = os.getenv("DATABASE_URL", "")
    _raw_jwt = os.getenv("JWT_SECRET", "")
    if not _raw_db_url.strip():
        MISSING_ENV_VARS.append("DATABASE_URL")
    if not _raw_jwt.strip():
        MISSING_ENV_VARS.append("JWT_SECRET")
    DATABASE_URL = normalize_database_url(_raw_db_url)
    JWT_SECRET = _raw_jwt.strip().strip('"').strip("'")
else:
    DATABASE_URL = normalize_database_url(os.environ["DATABASE_URL"])
    JWT_SECRET = os.environ["JWT_SECRET"].strip().strip('"').strip("'")

DIRECT_URL = normalize_database_url(os.getenv("DIRECT_URL", ""))

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
    if o.strip()
]
for _vercel_host_var in ("VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL", "VERCEL_BRANCH_URL"):
    _host = os.getenv(_vercel_host_var, "").strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    if _host and f"https://{_host}" not in CORS_ORIGINS:
        CORS_ORIGINS.append(f"https://{_host}")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "shika-uploads").strip() or "shika-uploads"