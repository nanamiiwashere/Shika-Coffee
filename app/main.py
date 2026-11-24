from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from psycopg2 import IntegrityError as PgIntegrityError
from psycopg2.errors import CheckViolation, ForeignKeyViolation, RestrictViolation, UniqueViolation
from sqlalchemy.exc import IntegrityError
from app.config import CORS_ORIGINS, IS_VERCEL, MISSING_ENV_VARS
from app.database import DB_INIT_ERROR
from app.routers import auth, inventory, master, reports, sales
from app.uploads import public_image_base, resolve_image_url

app = FastAPI(title="Shika Coffee POS & Inventory API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "app" / "static"
TEMPLATES_DIR = BASE_DIR / "app" / "templates"


@app.get("/static/images/{asset_path:path}", include_in_schema=False)
def static_image_asset(asset_path: str):
    cleaned = asset_path.lstrip("/")
    if not cleaned or ".." in cleaned.split("/"):
        raise HTTPException(status_code=404, detail="Not Found")
    resolved = resolve_image_url(f"/static/images/{cleaned}")
    if resolved and resolved.startswith("http"):
        return RedirectResponse(resolved, status_code=307, headers={"Cache-Control": "public, max-age=86400"})
    images_root = (STATIC_DIR / "images").resolve()
    file_path = (images_root / cleaned).resolve()
    if file_path.is_relative_to(images_root) and file_path.is_file():
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="Not Found")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR), check_dir=False), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["img_base"] = public_image_base
templates.env.globals["img_url"] = lambda rel: f"{public_image_base()}/{str(rel).lstrip('/')}"


@app.get("/", response_class=HTMLResponse)
def landing_page(request: Request):
    return templates.TemplateResponse(request, "landing.html")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    return templates.TemplateResponse(request, "signup.html")


@app.get("/pos", response_class=HTMLResponse)
def pos_page(request: Request):
    return templates.TemplateResponse(request, "pos.html")


@app.get("/pos/qris-pay/{session_id}", response_class=HTMLResponse)
def pos_qris_pay_page(request: Request, session_id: str):
    return templates.TemplateResponse(request, "qris_pay.html", {"session_id": session_id})


@app.get("/pos/orders", response_class=HTMLResponse)
@app.get("/orders", response_class=HTMLResponse)
def pos_orders_page(request: Request):
    return templates.TemplateResponse(request, "orders.html")


@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/reports-page", response_class=HTMLResponse)
def reports_page(request: Request):
    return templates.TemplateResponse(request, "reports.html")


def _integrity_response(err: object) -> JSONResponse:
    if isinstance(err, UniqueViolation):
        return JSONResponse(status_code=409, content={"detail": "Duplicate unique identifier (SKU, email, or name)"})
    if isinstance(err, (ForeignKeyViolation, RestrictViolation)):
        return JSONResponse(status_code=409, content={"detail": "Referenced record does not exist or is still in use"})
    if isinstance(err, CheckViolation):
        if "current_stock" in str(err):
            return JSONResponse(status_code=409, content={"detail": "Insufficient raw material stock"})
        return JSONResponse(status_code=400, content={"detail": "Database constraint violated"})
    return JSONResponse(status_code=400, content={"detail": "Database integrity error"})


@app.exception_handler(IntegrityError)
@app.exception_handler(PgIntegrityError)
def integrity_error_handler(_: Request, exc: Exception):
    return _integrity_response(getattr(exc, "orig", exc))


@app.get("/health")
def health():
    if IS_VERCEL and (MISSING_ENV_VARS or DB_INIT_ERROR or not TEMPLATES_DIR.is_dir()):
        return JSONResponse(
            status_code=503,
            content={
                "status": "misconfigured",
                "missing_env_vars": MISSING_ENV_VARS,
                "db_error": DB_INIT_ERROR,
                "templates_present": TEMPLATES_DIR.is_dir(),
            },
        )
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(master.router)
app.include_router(sales.router)
app.include_router(inventory.router)
app.include_router(reports.router)
