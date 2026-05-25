"""Survey router: 4 pages (prompt, pageA, pageB, demographics)."""

import logging

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import ValidationError

from database import get_db
from models.participant import Participant, Step
from models.survey import SurveyResponse
from routers.experiment import _get_participant, _redirect, _advance_step
from services.monitoring import log_event
from services.scales import (
    get_page_scales, get_page_likert_fields, get_page_custom_items,
    get_all_page_fields,
)
from schemas.survey import validate_likert_fields, DemographicsSubmit

router = APIRouter()
logger = logging.getLogger(__name__)


async def _get_or_create_survey(participant_id, db: AsyncSession) -> SurveyResponse:
    """Get existing survey response or create a new one."""
    result = await db.execute(
        select(SurveyResponse).where(SurveyResponse.participant_id == participant_id)
    )
    survey = result.scalar_one_or_none()
    if not survey:
        survey = SurveyResponse(participant_id=participant_id)
        db.add(survey)
        await db.commit()
        await db.refresh(survey)
    return survey


async def _extract_form_dict(request: Request, field_names: list[str]) -> dict:
    """Extract named fields from request.form(), converting to int."""
    raw = await request.form()
    result = {}
    for name in field_names:
        val = raw.get(name)
        if val is not None and val != "":
            try:
                result[name] = int(val)
            except (ValueError, TypeError):
                result[name] = val
        else:
            result[name] = None
    return result


def _render_survey(request, template: str, participant, error=None, form_data=None, page=None):
    """Render a survey template with scales data."""
    from routers.experiment import _participant_to_dict
    ctx = {
        "request": request,
        "p": _participant_to_dict(participant),
        "scales": get_page_scales(page) if page else [],
    }
    if error:
        ctx["error"] = error
    if form_data is not None:
        ctx["form_data"] = form_data
    return request.app.state.templates.TemplateResponse(template, ctx)


# ── Survey Prompt (instruction page, no form) ─────────────

@router.get("/survey/prompt", response_class=HTMLResponse)
async def survey_prompt(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)
    if participant.current_step != Step.survey_prompt:
        return await _redirect(participant, db)

    from routers.experiment import _participant_to_dict
    return request.app.state.templates.TemplateResponse("survey_prompt.html", {
        "request": request,
        "p": _participant_to_dict(participant),
    })


@router.post("/survey/prompt")
async def survey_prompt_submit(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    await _advance_step(participant, Step.survey_a, db)
    return RedirectResponse(url="/survey/a", status_code=303)


# ── Survey Page A ──────────────────────────────────────────

@router.get("/survey/a", response_class=HTMLResponse)
async def survey_page_a(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)
    if participant.current_step != Step.survey_a:
        return await _redirect(participant, db)

    return _render_survey(request, "survey_pageA.html", participant, page="A")


@router.post("/survey/a")
async def survey_page_a_submit(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    field_names = get_all_page_fields("A")
    form_data = await _extract_form_dict(request, field_names)

    error = validate_likert_fields(form_data, field_names)
    if error:
        return _render_survey(request, "survey_pageA.html", participant,
                              error="Please provide valid responses (values must be between 1 and 7).",
                              form_data=form_data, page="A")

    survey = await _get_or_create_survey(participant.id, db)
    for name, value in form_data.items():
        setattr(survey, name, value)
    await db.commit()

    await _advance_step(participant, Step.survey_b, db)
    return RedirectResponse(url="/survey/b", status_code=303)


# ── Survey Page B ──────────────────────────────────────────

@router.get("/survey/b", response_class=HTMLResponse)
async def survey_page_b(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)
    if participant.current_step != Step.survey_b:
        return await _redirect(participant, db)

    return _render_survey(request, "survey_pageB.html", participant, page="B")


@router.post("/survey/b")
async def survey_page_b_submit(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    custom_items = get_page_custom_items("B")
    likert_fields = get_page_likert_fields("B")
    all_fields = [ci.field_name for ci in custom_items] + likert_fields
    form_data = await _extract_form_dict(request, all_fields)

    # Validate custom items with their own ranges
    error = None
    for ci in custom_items:
        val = form_data.get(ci.field_name)
        if val is not None:
            if not isinstance(val, int) or val < ci.min_val or val > ci.max_val:
                error = "Please provide valid responses."
                break

    # Validate Likert fields (1-7)
    if not error:
        error = validate_likert_fields(form_data, likert_fields)

    if error:
        return _render_survey(request, "survey_pageB.html", participant,
                              error="Please provide valid responses (values must be between 1 and 7).",
                              form_data=form_data, page="B")

    survey = await _get_or_create_survey(participant.id, db)
    for name, value in form_data.items():
        setattr(survey, name, value)
    await db.commit()

    await _advance_step(participant, Step.survey_c, db)
    return RedirectResponse(url="/survey/c", status_code=303)


# ── Survey Page C (Outcome Variables) ─────────────────────

@router.get("/survey/c", response_class=HTMLResponse)
async def survey_page_c(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)
    if participant.current_step != Step.survey_c:
        return await _redirect(participant, db)

    return _render_survey(request, "survey_pageC.html", participant, page="C")


@router.post("/survey/c")
async def survey_page_c_submit(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    field_names = get_all_page_fields("C")
    form_data = await _extract_form_dict(request, field_names)

    error = validate_likert_fields(form_data, field_names)
    if error:
        return _render_survey(request, "survey_pageC.html", participant,
                              error="Please provide valid responses (values must be between 1 and 7).",
                              form_data=form_data, page="C")

    survey = await _get_or_create_survey(participant.id, db)
    for name, value in form_data.items():
        setattr(survey, name, value)
    await db.commit()

    await _advance_step(participant, Step.demographics, db)
    return RedirectResponse(url="/survey/demographics", status_code=303)


# ── Demographics ───────────────────────────────────────────

@router.get("/survey/demographics", response_class=HTMLResponse)
async def demographics_page(request: Request, db: AsyncSession = Depends(get_db)):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)
    if participant.current_step != Step.demographics:
        return await _redirect(participant, db)

    return _render_survey(request, "demographics.html", participant, page="demographics")


@router.post("/survey/demographics")
async def demographics_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    age: int | None = Form(default=None),
    gender: str | None = Form(default=None),
    race: str | None = Form(default=None),
    education: str | None = Form(default=None),
    partisanship: str | None = Form(default=None),
):
    participant = await _get_participant(request, db)
    if not participant:
        return RedirectResponse(url="/consent", status_code=303)

    # Extract Likert fields dynamically
    likert_fields = get_page_likert_fields("demographics")
    form_raw = await request.form()

    form_data: dict = {
        "age": age, "gender": gender, "race": race,
        "education": education, "partisanship": partisanship,
    }
    for name in likert_fields:
        val = form_raw.get(name)
        form_data[name] = int(val) if val is not None else None

    # Validate demographic structural fields
    validation_error = None
    if age is None or age < 18 or age > 120:
        validation_error = "Please enter a valid age (18-120)."
    elif not gender:
        validation_error = "Please select your gender."
    elif not race:
        validation_error = "Please select your race/ethnicity."
    elif not education:
        validation_error = "Please select your education level."
    elif not partisanship:
        validation_error = "Please select your political orientation."

    if not validation_error:
        try:
            DemographicsSubmit(**{k: form_data[k] for k in ["age", "gender", "race", "education", "partisanship"]})
        except ValidationError:
            validation_error = "Please complete all fields with valid responses."

    if not validation_error:
        validation_error = validate_likert_fields(form_data, likert_fields)

    if validation_error:
        return _render_survey(request, "demographics.html", participant,
                              error=validation_error, form_data=form_data,
                              page="demographics")

    survey = await _get_or_create_survey(participant.id, db)
    survey.age = age
    survey.gender = gender
    survey.race = race
    survey.education = education
    survey.partisanship = partisanship
    for name in likert_fields:
        setattr(survey, name, form_data[name])
    await db.commit()

    await log_event(db, participant.id, "survey_completed", "demographics")
    await _advance_step(participant, Step.payment, db)
    return RedirectResponse(url="/payment", status_code=303)
