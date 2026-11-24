import os
from pathlib import Path
from urllib.parse import quote


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
    url = raw_url.strip()
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
    return url


load_dotenv_if_present()

DATABASE_URL = normalize_database_url(os.environ["DATABASE_URL"])
DIRECT_URL = normalize_database_url(os.getenv("DIRECT_URL", ""))
JWT_SECRET = os.environ["JWT_SECRET"]
IS_VERCEL = bool(os.getenv("VERCEL"))

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
    if o.strip()
]
_vercel_url = os.getenv("VERCEL_URL", "").strip().removeprefix("https://").removeprefix("http://").rstrip("/")
if _vercel_url and f"https://{_vercel_url}" not in CORS_ORIGINS:
    CORS_ORIGINS.append(f"https://{_vercel_url}")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "shika-uploads").strip() or "shika-uploads"