"""Bulk import API (spec §21): template download, upload, job status."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record
from app.auth.deps import get_current_user
from app.config import get_settings
from app.db.session import get_db
from app.imports import service
from app.logging import request_id_var
from app.models import AppUser, BulkImportJob
from app.models.enums import AuditAction, JobStatus

router = APIRouter(prefix="/api/v1/bulk-import", tags=["bulk-import"])


@router.get("/template")
def template(
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    content, filename = service.build_template(db, user)
    return PlainTextResponse(
        content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("", status_code=202)
async def upload(
    request: Request,
    file: UploadFile,
    period_id: uuid.UUID,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if file.content_type not in ("text/csv", "application/vnd.ms-excel", "application/octet-stream"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Only CSV files are accepted")
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="CSV exceeds the 5 MB limit")
    settings = get_settings()
    job_id = uuid.uuid4()
    object_key = f"imports/{job_id}/{file.filename or 'import.csv'}"
    import io

    from app.infra import storage

    storage.get_client().put_object(
        settings.s3_bucket, object_key, io.BytesIO(content),
        length=len(content), content_type="text/csv",
    )
    job = BulkImportJob(
        id=job_id,
        uploaded_by=user.id,
        period_id=period_id,
        file_object_key=object_key,
        original_filename=file.filename or "import.csv",
        status=JobStatus.PENDING,
    )
    db.add(job)
    db.flush()
    record(
        db, action=AuditAction.CREATED, object_type="bulk_import_job", object_id=job.id,
        actor_id=user.id, actor_label=user.email,
        new_value={"filename": job.original_filename}, request_id=request_id_var.get(),
    )
    db.commit()

    from app.workers.tasks import process_bulk_import as task

    task.delay(str(job.id), str(user.id))
    return {"job_id": str(job.id), "status": "PENDING"}


@router.get("/{job_id}")
def job_status(
    job_id: uuid.UUID,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    job = db.get(BulkImportJob, job_id)
    if job is None or job.uploaded_by != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import job not found")
    return {
        "job_id": str(job.id),
        "status": job.status.value,
        "total_rows": job.total_rows,
        "valid_rows": job.valid_rows,
        "invalid_rows": job.invalid_rows,
        "error_report_object_key": job.error_report_object_key,
        "error": job.error,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
    }
