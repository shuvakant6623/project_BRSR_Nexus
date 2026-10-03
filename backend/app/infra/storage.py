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


def presigned_get(object_key: str, expires_hours: float = 1.0) -> str:
    """Pre-signed GET whose host is rewritten to the public endpoint so the
    URL works from the browser (signature covers path + query, not host)."""
    from datetime import timedelta
    from urllib.parse import urlparse

    settings = get_settings()
    url = get_client().presigned_get_object(
        settings.s3_bucket, object_key, expires=timedelta(hours=expires_hours)
    )
    public = getattr(settings, "s3_public_endpoint", "") or ""
    if public:
        p, pub = urlparse(url), urlparse(public)
        url = url.replace(f"{p.scheme}://{p.netloc}", f"{pub.scheme}://{pub.netloc}", 1)
    return url
