"""RFC 7807-style problem+json error responses."""
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def problem_detail(
    type_uri: str,
    title: str,
    status_code: int,
    detail: str | None = None,
    errors: list[dict] | None = None,
) -> dict:
    body: dict = {"type": type_uri, "title": title, "status": status_code}
    if detail:
        body["detail"] = detail
    if errors:
        body["errors"] = errors
    return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=problem_detail(
                type_uri="validation_error",
                title="Validation failed",
                status_code=422,
                detail="The request payload failed validation",
                errors=[
                    {"field": ".".join(str(loc) for loc in err["loc"]), "message": err["msg"]}
                    for err in exc.errors()
                ],
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content=problem_detail(
                type_uri="internal_error",
                title="Internal server error",
                status_code=500,
                detail="An unexpected error occurred. Reference: "
                + str(getattr(request.state, "request_id", "")),
            ),
        )
