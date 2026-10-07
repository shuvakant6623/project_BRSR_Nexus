"""S3-compatible object storage client (RustFS, MinIO, AWS S3, ...).

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


def _public_client() -> Minio:
    """A client bound to the browser-reachable endpoint. SigV4 signs the Host
    header, so presigning must happen against the SAME host the client will
    fetch from — rewriting the host after signing breaks the signature."""
    from urllib.parse import urlparse

    settings = get_settings()
    pub = urlparse(settings.s3_public_endpoint)
    # region pinned: the SDK otherwise performs a bucket-location lookup
    # against this endpoint, which is unreachable from inside the cluster
    return Minio(
        pub.netloc,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        secure=pub.scheme == "https",
        region="us-east-1",
    )


def presigned_get(object_key: str, expires_hours: float = 1.0) -> str:
    """Pre-signed, time-limited GET. When S3_PUBLIC_ENDPOINT is configured the
    signature is generated for that host so the URL works from the browser."""
    from datetime import timedelta

    settings = get_settings()
    client = _public_client() if settings.s3_public_endpoint else get_client()
    return client.presigned_get_object(
        settings.s3_bucket, object_key, expires=timedelta(hours=expires_hours)
    )
