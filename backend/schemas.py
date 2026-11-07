"""Shared API v1 models, including schemas reserved for real RAG results."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProgramId = Literal["computer_engineering", "medicine", "physical_education", "vehicle_engineering"]


class AcademicContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    program_id: ProgramId
    plan_version: str = Field(pattern=r"^20[0-9]{2}-[1-9]$")
    completed_course_codes: list[Annotated[str, Field(pattern=r"^[0-9]{7,9}$")]] = Field(default_factory=list, max_length=400)
    user_declared_completed_credits: float | None = Field(default=None, ge=0, le=400, allow_inf_nan=False)

    @field_validator("completed_course_codes")
    @classmethod
    def unique_codes(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("يجب ألا تكون الرسالة فارغة.")
        return value


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=8)
    academic_context: AcademicContext | None = None

    @field_validator("question")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("يجب ألا يكون السؤال فارغاً.")
        return value


class HealthResponse(BaseModel):
    status: Literal["degraded"] = "degraded"
    index_ready: bool = False
    llm_configured: bool
    documents_count: int = Field(default=0, ge=0)
    chunks_count: int = Field(default=0, ge=0)


class Citation(BaseModel):
    source_id: str
    document_id: str
    title: str
    filename: str
    page: int | None = Field(ge=1, description="رقم صفحة PDF الفعلي بدءاً من 1؛ null لمصدر HTML مع موضع في article.")
    article: str | None = None
    quote: str


class ChatResponse(BaseModel):
    request_id: str
    status: Literal[
        "answered", "insufficient_evidence", "out_of_scope", "needs_clarification"
    ]
    answer: str
    citations: list[Citation]
    latency_ms: int = Field(ge=0)


class DocumentEntry(BaseModel):
    document_id: str
    title: str
    filename: str
    page_count: int | None = Field(ge=1)


class DocumentsResponse(BaseModel):
    documents: list[DocumentEntry] = Field(default_factory=list)


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class CreditGroup(BaseModel):
    name_ar: str
    required_credits: float = Field(ge=0)
    is_elective: bool


class SourceLocator(BaseModel):
    page: int | None = Field(default=None, ge=1)
    section: str
    article: str | None = None
    course_code: str | None = None
    major_code: str | None = None


class PlanSummary(BaseModel):
    plan_version: str
    total_required_credits: float = Field(ge=0)
    credit_groups: list[CreditGroup]
    course_count: int = Field(ge=0)
    course_coverage: str
    is_partial: bool
    coverage_limitations: list[str]
    document_id: str
    source_locator: SourceLocator


class ProgramEntry(BaseModel):
    program_id: ProgramId
    program_name_ar: str
    major_code: str
    faculty_name_ar: str | None = None
    plans: list[PlanSummary]


class ProgramsResponse(BaseModel):
    programs: list[ProgramEntry]


class CourseEntry(BaseModel):
    course_code: str
    course_name_ar: str
    course_name_en: str | None = None
    credits: float = Field(ge=0)
    requirement_group_ar: str
    document_id: str
    source_locator: SourceLocator
    prerequisite_status: str
    prerequisite_expression_raw: str | None


class PlanCoursesResponse(BaseModel):
    program_id: ProgramId
    plan: PlanSummary
    courses: list[CourseEntry]
