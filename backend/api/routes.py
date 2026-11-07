from time import perf_counter

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from groq import APIConnectionError, APIStatusError, APITimeoutError

from backend.config import get_settings
from backend.schemas import (
    ChatRequest,
    ChatResponse,
    DocumentsResponse,
    DocumentEntry,
    ErrorResponse,
    HealthResponse,
    ProgramsResponse,
    PlanCoursesResponse,
)
from backend.services import catalog, rag
from backend.services.llm import IncompleteCompletionError, rate_limit_category, rate_limit_headers
from backend.services.retrieval import PROJECT_ROOT, get_catalog, get_index

router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    index = get_index()
    catalog, count = (index.documents, len(index.chunks)) if index else get_catalog()
    return HealthResponse(llm_configured=get_settings().llm_configured, index_ready=index is not None,
                          documents_count=len(catalog), chunks_count=count)


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={code: {"model": ErrorResponse} for code in (422, 429, 502, 503, 504)},
)
def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    started = perf_counter()
    index = get_index()
    if index is None:
        raise HTTPException(status_code=503)
    if payload.academic_context is not None:
        try:
            catalog.validate_context(index, payload.academic_context)
        except ValueError:
            raise HTTPException(status_code=422) from None
    try:
        status, text, citations = rag.answer(payload, index, get_settings(), request_id=request.state.request_id)
    except APITimeoutError:
        raise HTTPException(status_code=504, detail="LLM_TIMEOUT") from None
    except APIConnectionError:
        raise HTTPException(status_code=502, detail="LLM_UNAVAILABLE") from None
    except IncompleteCompletionError:
        raise HTTPException(status_code=502, detail="LLM_UNAVAILABLE") from None
    except APIStatusError as exc:
        if exc.status_code == 429:
            retry_after = rate_limit_headers(exc)["retry-after"]
            detail = "LLM_DAILY_QUOTA" if rate_limit_category(exc) in {"RPD", "TPD"} else "LLM_RATE_LIMIT"
            raise HTTPException(status_code=429, detail=detail,
                                headers={"Retry-After": retry_after} if retry_after is not None else None) from None
        raise HTTPException(status_code=502, detail="LLM_UNAVAILABLE") from None
    return ChatResponse(request_id=request.state.request_id, status=status, answer=text,
                        citations=citations, latency_ms=round((perf_counter() - started) * 1000))


@router.get("/programs", response_model=ProgramsResponse, responses={503: {"model": ErrorResponse}})
def programs() -> ProgramsResponse:
    index = get_index()
    if index is None:
        raise HTTPException(status_code=503, detail="CATALOG_UNAVAILABLE")
    return ProgramsResponse(programs=catalog.programs(index))


@router.get("/programs/{program_id}/plans/{plan_version}/courses", response_model=PlanCoursesResponse,
            responses={code: {"model": ErrorResponse} for code in (404, 503)})
def plan_courses(program_id: str, plan_version: str) -> PlanCoursesResponse:
    index = get_index()
    if index is None:
        raise HTTPException(status_code=503, detail="CATALOG_UNAVAILABLE")
    try:
        plan = catalog.selected_plan(index, program_id, plan_version)
    except ValueError:
        raise HTTPException(status_code=404) from None
    return PlanCoursesResponse(program_id=program_id, plan=catalog.plan_summary(plan),
                               courses=catalog.courses(index, program_id, plan_version))


@router.get("/documents", response_model=DocumentsResponse)
def documents() -> DocumentsResponse:
    index = get_index()
    catalog, _ = (index.documents, len(index.chunks)) if index else get_catalog()
    return DocumentsResponse(documents=[DocumentEntry(**doc) for doc in catalog.values()])


@router.get(
    "/documents/{document_id}/file", responses={404: {"model": ErrorResponse}}
)
def document_file(document_id: str) -> FileResponse:
    index = get_index()
    catalog, _ = (index.documents, len(index.chunks)) if index else get_catalog()
    if document_id not in catalog:
        raise HTTPException(status_code=404)
    doc = catalog[document_id]
    path = (PROJECT_ROOT / doc["relative_path"]).resolve()
    raw = (PROJECT_ROOT / "data/data/raw").resolve()
    if not path.is_relative_to(raw) or not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, filename=doc["filename"], media_type="application/octet-stream",
                        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})
