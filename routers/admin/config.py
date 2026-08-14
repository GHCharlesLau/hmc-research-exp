"""Admin config editor."""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models.experiment import ExperimentConfig
from routers.admin.auth import require_admin

router = APIRouter()

CONFIG_KEYS = {
    "CHARACTER_PROMPT_A": "Emotion task + MyBot (AI) prompt",
    "CHARACTER_PROMPT_Afake": "Emotion task + Tommy (fake human) prompt",
    "CHARACTER_PROMPT_B": "Function task + MyBot (AI) prompt",
    "CHARACTER_PROMPT_Bfake": "Function task + Tommy (fake human) prompt",
    "default_model": "LLM model name (e.g., gpt-4o-mini)",
    "min_turns": "Minimum chat turns before Next button enabled",
    "max_turns": "Maximum chat turns (auto-end)",
    "max_duration": "Chat max duration in seconds",
}


@router.get("/admin/config", response_class=HTMLResponse)
async def config_page(request: Request, db: AsyncSession = Depends(get_db), _auth=Depends(require_admin)):
    if _auth:
        return _auth
    result = await db.execute(select(ExperimentConfig).order_by(ExperimentConfig.key))
    configs = result.scalars().all()
    config_dict = {c.key: c for c in configs}
    return request.app.state.templates.TemplateResponse("admin/config.html", {
        "request": request,
        "nav": "config",
        "config_dict": config_dict,
        "config_keys": CONFIG_KEYS,
    })


@router.post("/admin/config")
async def config_update(request: Request, db: AsyncSession = Depends(get_db), _auth=Depends(require_admin)):
    if _auth:
        return _auth
    form = await request.form()
    for key in CONFIG_KEYS:
        value = form.get(key, "")
        result = await db.execute(
            select(ExperimentConfig).where(ExperimentConfig.key == key)
        )
        config = result.scalar_one_or_none()
        if config:
            config.value = str(value)
        elif value:
            config = ExperimentConfig(key=key, value=str(value), description=CONFIG_KEYS[key])
            db.add(config)
    await db.commit()
    from services.llm import invalidate_config_cache
    invalidate_config_cache()
    return RedirectResponse(url="/admin/config", status_code=303)
