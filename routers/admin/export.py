"""Admin CSV export."""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from services.export import export_participant_table, export_chat_messages
from routers.admin.auth import require_admin, _verify_admin_session

router = APIRouter()


@router.get("/admin/export", response_class=HTMLResponse)
async def export_page(request: Request, _auth=Depends(require_admin)):
    if _auth:
        return _auth
    return request.app.state.templates.TemplateResponse("admin/data_export.html", {
        "request": request,
        "nav": "export",
    })


@router.get("/admin/export/{format_type}")
async def export_data(
    request: Request,
    format_type: str,
    include_test: bool = False,
    exclude_timeout: bool = False,
    exclude_dropout: bool = False,
    exclude_over_max: bool = False,
    db: AsyncSession = Depends(get_db),
):
    auth_error = await _verify_admin_session(request)
    if auth_error:
        return auth_error

    filters = dict(
        include_test=include_test,
        exclude_timeout=exclude_timeout,
        exclude_dropout=exclude_dropout,
        exclude_over_max=exclude_over_max,
    )
    if format_type == "participants":
        csv_data = await export_participant_table(db, **filters)
        filename = "participants.csv"
    elif format_type == "chat":
        csv_data = await export_chat_messages(db, **filters)
        filename = "chat_messages.csv"
    else:
        return JSONResponse({"detail": "Invalid format"}, status_code=400)

    return JSONResponse(
        content={"csv": csv_data, "filename": filename},
        media_type="application/json",
    )
