"""Health and readiness endpoints.

/healthz  — API process alive (no dependency checks).
/readyz   — PostgreSQL, Redis and object storage reachable; 503 otherwise.
"""
from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import text

from app.config import get_settings
from app.db.session import engine
from app.infra import storage

router = APIRouter(tags=["health"])


def _check_postgres() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _check_redis() -> bool:
    try:
        import redis

        client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
        return bool(client.ping())
    except Exception:
        return False


class DependencyStatus(BaseModel):
    postgres: bool
    redis: bool
    s3: bool


class ReadyResponse(BaseModel):
    status: str
    dependencies: DependencyStatus


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(response: Response) -> ReadyResponse:
    deps = DependencyStatus(
        postgres=_check_postgres(),
        redis=_check_redis(),
        s3=storage.ping(),
    )
    ok = all(deps.model_dump().values())
    if not ok:
        response.status_code = 503
    return ReadyResponse(status="ready" if ok else "degraded", dependencies=deps)
