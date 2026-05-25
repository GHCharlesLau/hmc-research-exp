"""Error pages and global exception handler."""

import logging

from fastapi import Request
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)


async def not_found_handler(request: Request, exc):
    return request.app.state.templates.TemplateResponse("404.html", {
        "request": request,
    }, status_code=404)


async def server_error_handler(request: Request, exc):
    logger.error(f"500 error: {exc}")
    return request.app.state.templates.TemplateResponse("500.html", {
        "request": request,
    }, status_code=500)
