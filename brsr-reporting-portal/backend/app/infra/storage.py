"""MinIO / S3-compatible object storage client.

Only metadata operations live here; the storage layer is intentionally
S3-compatible so it can be pointed at real AWS S3 via environment variables.
"""
import logging

from minio import Minio
from minio.error import S3Error

from app.config import get_settings

logger = logging.getLogger(__name__)


def get_client() -> Minio:
    settings = get_settings()
    return Minio(
        settings.s3_endpoint.replace("http://", "").replace("https://", ""),
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        secure=settings.s3_endpoint.startswith("https://"),
    )


def ensure_bucket() -> None:
    settings = get_settings()
    client = get_client()
    if not client.bucket_exists(settings.s3_bucket):
        client.make_bucket(settings.s3_bucket)
        logger.info("created bucket", extra={"job_id": settings.s3_bucket})


def ping() -> bool:
    try:
        get_client().bucket_exists(get_settings().s3_bucket)
        return True
    except S3Error:
        return False
    except Exception:
        return False
