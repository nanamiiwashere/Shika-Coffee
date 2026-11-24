import logging
import re
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_CRED_RE = re.compile(r"://[^@\s/]+@")


def _redact(text: str) -> str:
    return _CRED_RE.sub("://***:***@", text)


try:
    from app.main import app
except Exception as exc:
    logging.exception("Failed to initialize Shika Coffee FastAPI app")
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    _err_msg = _redact(f"{type(exc).__name__}: {exc}")
    _trace_tail = [_redact(line) for line in traceback.format_exc().splitlines()[-8:]]
    app = FastAPI(title="Shika Coffee (Startup Diagnostic)")

    @app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def _startup_error(full_path: str):
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Shika Coffee failed during cold start",
                "error": _err_msg,
                "hint": "Check Vercel Environment Variables (DATABASE_URL, JWT_SECRET) and Runtime Logs.",
                "trace_tail": _trace_tail,
            },
        )
