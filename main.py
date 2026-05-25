"""FastAPI entry point for ConExperiment 2.0."""

import logging
import os
from contextlib import asynccontextmanager

import typer
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import get_settings
from routers import experiment, survey, chat, admin, errors, ws

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("Starting ConExperiment 2.0")
    if settings.DEMO_MODE:
        logger.info("[DEMO MODE] Enabled - Reduced turns/timeouts, Prolific checks disabled")
    yield
    logger.info("Shutting down ConExperiment 2.0")


app = FastAPI(title="ConExperiment 2.0", lifespan=lifespan)

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates
templates = Jinja2Templates(directory="templates")
app.state.templates = templates

# Routers
app.include_router(experiment.router)
app.include_router(survey.router)
app.include_router(chat.router)
app.include_router(admin.router)
app.include_router(ws.router)

# Error handlers
app.add_exception_handler(404, not_found_handler := errors.not_found_handler)
app.add_exception_handler(500, server_error_handler := errors.server_error_handler)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


# =============================================================================
# CLI Entry Point (typer)
# =============================================================================

cli = typer.Typer(add_completion=False, help="ConExperiment 2.0 - Online conversation experiment platform")


@cli.command()
def run(
    demo: bool = typer.Option(False, "--demo", help="Enable demo mode (reduced turns/timeouts, skip Prolific checks)"),
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind to"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind to"),
    reload: bool = typer.Option(False, "--reload", "-r", help="Enable auto-reload for development"),
):
    """Start the ConExperiment 2.0 server."""
    if demo:
        os.environ["DEMO_MODE"] = "true"
        typer.echo("[DEMO MODE] Enabled")

    import uvicorn
    import logging

    display_host = "localhost" if host == "0.0.0.0" else host
    typer.echo(f"\n  Server running at http://{display_host}:{port}")
    typer.echo(f"  Admin dashboard: http://{display_host}:{port}/admin/dashboard\n")

    class _SuppressUvicornAddr(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return "Uvicorn running on" not in record.getMessage()

    logging.getLogger("uvicorn.error").addFilter(_SuppressUvicornAddr())

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=reload,
        workers=1,  # Always 1 worker for WebSocket compatibility
    )


@cli.command()
def version():
    """Show version information."""
    typer.echo("ConExperiment 2.0")
    typer.echo("Tech Stack: FastAPI, SQLAlchemy, Redis, WebSocket, LiteLLM")


if __name__ == "__main__":
    cli()
