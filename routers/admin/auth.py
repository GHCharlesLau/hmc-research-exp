"""Admin authentication: login, logout, session checks.

Password hashing: the current env var ``ADMIN_PASSWORD_HASH`` is an unsalted
SHA-256 hex digest (legacy). To migrate to bcrypt:

1. Generate a bcrypt hash: ``python -c "import bcrypt; print(bcrypt.hashpw(b'PASSWORD', bcrypt.gensalt()).decode())"``
2. Store the ``$2b$...`` value in ``ADMIN_PASSWORD_HASH``.
3. Replace ``_verify_password`` to call ``bcrypt.checkpw`` when the stored
   hash starts with ``$2b$`` or ``$2a$``, keeping SHA-256 as a fallback until
   all deployments are rotated.
"""

import hashlib
import logging
import secrets

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from services.auth import ADMIN_COOKIE_NAME, set_admin_cookie
from services.matchmaking import get_redis
from config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

LOGIN_FAIL_PREFIX = "admin_login_fail:"
LOGIN_FAIL_LIMIT = 10
LOGIN_FAIL_WINDOW = 300


def _verify_password(password: str) -> bool:
    """Verify admin password against stored SHA-256 hash (see module docstring)."""
    if not settings.ADMIN_PASSWORD_HASH:
        return False
    pwd_hash = hashlib.sha256(password.encode()).hexdigest()
    return pwd_hash == settings.ADMIN_PASSWORD_HASH


async def _login_fail_count(request: Request) -> int:
    ip = request.client.host if request.client else "unknown"
    r = await get_redis()
    val = await r.get(f"{LOGIN_FAIL_PREFIX}{ip}")
    return int(val) if val else 0


async def _record_login_failure(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    r = await get_redis()
    key = f"{LOGIN_FAIL_PREFIX}{ip}"
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, LOGIN_FAIL_WINDOW)


async def _clear_login_failures(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    r = await get_redis()
    await r.delete(f"{LOGIN_FAIL_PREFIX}{ip}")


async def _verify_admin_session(request: Request) -> JSONResponse | None:
    """Verify admin session for API endpoints. Returns None if valid."""
    token = request.cookies.get(ADMIN_COOKIE_NAME)
    if not token:
        return JSONResponse({"detail": "Unauthorized: admin token missing"}, status_code=401)

    r = await get_redis()
    session_exists = await r.get(f"admin_session:{token}")
    if not session_exists:
        return JSONResponse({"detail": "Unauthorized: invalid or expired session"}, status_code=401)

    return None


async def require_admin(request: Request) -> RedirectResponse | None:
    """Dependency for admin page routes. Returns redirect if invalid, None if valid."""
    token = request.cookies.get(ADMIN_COOKIE_NAME)
    if not token:
        return RedirectResponse(url="/admin/login", status_code=303)
    try:
        r = await get_redis()
        valid = await r.get(f"admin_session:{token}")
        if valid:
            return None
    except Exception as e:
        logger.error(f"Admin auth Redis error: {e}")
    return RedirectResponse(url="/admin/login", status_code=303)


@router.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return request.app.state.templates.TemplateResponse("admin/login.html", {
        "request": request,
    })


@router.post("/admin/login")
async def login_submit(request: Request, password: str = Form(...)):
    if await _login_fail_count(request) >= LOGIN_FAIL_LIMIT:
        return request.app.state.templates.TemplateResponse("admin/login.html", {
            "request": request,
            "error": "Too many login attempts. Please try again later.",
        })
    if _verify_password(password):
        await _clear_login_failures(request)
        token = secrets.token_urlsafe(32)
        r = await get_redis()
        await r.setex(f"admin_session:{token}", 86400, "1")
        response = RedirectResponse(url="/admin/dashboard", status_code=303)
        set_admin_cookie(response, token)
        return response
    await _record_login_failure(request)
    return request.app.state.templates.TemplateResponse("admin/login.html", {
        "request": request,
        "error": "Invalid password",
    })


@router.get("/admin/logout")
async def admin_logout(request: Request):
    token = request.cookies.get(ADMIN_COOKIE_NAME)
    if token:
        r = await get_redis()
        await r.delete(f"admin_session:{token}")
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(ADMIN_COOKIE_NAME)
    return response
