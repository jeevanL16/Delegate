"""FastAPI application entrypoint."""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.logging_conf import configure_logging
from app.routes import health, human, tickets

configure_logging()

app = FastAPI(
    title="Delegate: Resolve",
    description="AI-powered customer support ticket resolution system",
    version="1.0.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)

# CORS — restricted to named origins only (no wildcard in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "name": "Delegate: Resolve API",
        "status": "healthy",
        "version": "1.0.0",
        "health_check": "/health"
    }

app.include_router(health.router)
app.include_router(tickets.router)
app.include_router(human.router)


# ── Global exception handler — never leak stack traces or internal paths ──────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Log the full error server-side
    import logging
    logging.getLogger(__name__).exception("Unhandled exception on %s %s", request.method, request.url.path)
    # Return sanitized error to client
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_server_error", "message": "An internal error occurred"}},
    )
