import logging
from typing import Generator

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db

logger = logging.getLogger(__name__)


# ── API Key auth (service-to-service) ────────────────────────────────────────

def require_api_key(x_api_key: str = Header(alias="X-API-Key")) -> None:
    if x_api_key != settings.service_api_key:
        logger.warning("Invalid API key attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_api_key", "message": "Invalid or missing API key"},
        )


# ── JWT auth (human agents) ───────────────────────────────────────────────────

def require_human_agent(authorization: str = Header()) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "invalid_token", "message": "Invalid or expired token"},
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not authorization.startswith("Bearer "):
        raise credentials_exception
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(token, settings.human_jwt_secret, algorithms=["HS256"])
        role: str = payload.get("role", "")
        if role != "human_agent":
            raise credentials_exception
        return payload
    except JWTError:
        raise credentials_exception


# ── DB dependency ─────────────────────────────────────────────────────────────

def get_session() -> Generator:  # type: ignore[type-arg]
    yield from get_db()
