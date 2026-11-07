"""Application wiring; startup and health checks never contact Groq."""

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from backend.api.routes import router
from backend.config import get_settings
from backend.schemas import ErrorDetail, ErrorResponse

settings = get_settings()
app = FastAPI(title="Academic Advisor API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    expose_headers=["X-Request-ID", "Retry-After"],
)


@app.middleware("http")
async def assign_request_id(request: Request, call_next):
    request.state.request_id = str(uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


def error_response(request: Request, status: int, code: str, message: str, retry_after: str | None = None):
    request_id = getattr(request.state, "request_id", None) or str(uuid4())
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message, request_id=request_id)
    )
    headers = {"X-Request-ID": request_id}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return JSONResponse(
        status_code=status,
        content=body.model_dump(),
        headers=headers,
    )


@app.exception_handler(HTTPException)
async def handle_http_error(request: Request, exc: HTTPException):
    provider_errors = {
        "CATALOG_UNAVAILABLE": ("CATALOG_UNAVAILABLE", "كتالوج البرامج والمقررات غير متاح حالياً. أعد المحاولة لاحقاً."),
        "LLM_NOT_CONFIGURED": ("LLM_NOT_CONFIGURED", "لم يتم إعداد خدمة الإجابة بعد."),
        "LLM_TIMEOUT": ("LLM_TIMEOUT", "انتهت مهلة خدمة الإجابة. حاول لاحقاً."),
        "LLM_RATE_LIMIT": ("LLM_RATE_LIMIT", "بلغت خدمة Groq حد الاستخدام. راجع الحصة المتاحة ومدة التهدئة إن توفرت."),
        "LLM_DAILY_QUOTA": ("LLM_RATE_LIMIT", "استُنفدت حصة Groq اليومية. يلزم تجدد الحصة أو تعديلها؛ الانتظار القصير ليس حلاً مضموناً."),
        "LLM_UNAVAILABLE": ("LLM_UNAVAILABLE", "خدمة الإجابة غير متاحة حالياً. حاول لاحقاً."),
    }
    if isinstance(exc.detail, str) and exc.detail in provider_errors:
        code, message = provider_errors[exc.detail]
        retry_after = (exc.headers or {}).get("Retry-After") if exc.status_code == 429 else None
        return error_response(request, exc.status_code, code, message, retry_after)
    code, message = {
        404: ("NOT_FOUND", "المورد المطلوب غير موجود."),
        405: ("METHOD_NOT_ALLOWED", "طريقة الطلب غير مسموحة."),
        422: ("VALIDATION_ERROR", "بيانات الطلب غير صالحة. راجع الحقول والحدود الموثقة."),
        503: ("KNOWLEDGE_NOT_READY", "لم يتم تجهيز مستندات الجامعة بعد."),
    }.get(exc.status_code, ("HTTP_ERROR", "تعذر تنفيذ الطلب."))
    return error_response(request, exc.status_code, code, message)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    # Do not echo rejected inputs, which may contain sensitive user content.
    return error_response(
        request, 422, "VALIDATION_ERROR", "بيانات الطلب غير صالحة. راجع الحقول والحدود الموثقة."
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    return error_response(
        request, 500, "INTERNAL_ERROR", "حدث خطأ داخلي. يرجى المحاولة لاحقاً."
    )


app.include_router(router)
