"""Read-only public projections of the four validated, loaded target plans."""

from backend.schemas import AcademicContext, CourseEntry, PlanSummary, ProgramEntry
from backend.services.ingestion import TARGETS
from backend.services.retrieval import RetrievalIndex, normalize


def selected_plan(index: RetrievalIndex, program_id: str, plan_version: str) -> dict:
    if program_id not in TARGETS or TARGETS[program_id][1] != plan_version:
        raise ValueError("Unsupported program/plan")
    plan = index.programs.get(program_id)
    if plan is None or plan["plan_version"] != plan_version or plan["major_code"] != TARGETS[program_id][0]:
        raise ValueError("Plan is unavailable")
    return plan


def plan_summary(plan: dict) -> PlanSummary:
    partial = plan["course_coverage"] != "all_rows_in_supplied_public_html"
    limitations = ["القائمة من المصادر المتاحة؛ ليست تدقيق تخرج رسمياً، والاختيارات البديلة لا يلزم إكمالها جميعاً."]
    if partial:
        limitations += [
            f"مصدر المركبات تفريغ مشتق جزئي: المتاح {plan['course_rows']} صفاً من المقررات المطلوبة فقط، وليست خطة تخرج مكتملة.",
            "خيارات المقررات الاختيارية والمتطلبات السابقة الرسمية غير متوفرة.",
            "لوحة الساعات الحرة المنفصلة غير محسومة؛ لا تُضاف تلقائياً إلى المجموع.",
        ]
    if plan.get("known_conflicts") and not partial:
        limitations.append("توجد فروق بين نسخة الخطة وملخص الدليل؛ لا تُدمج النسختان في مجموع واحد.")
    return PlanSummary(
        plan_version=plan["plan_version"], total_required_credits=plan["total_required_credits"],
        credit_groups=[{**group, "name_ar": group["name_ar"].strip(),
                        "is_elective": any(word in normalize(group["name_ar"]) for word in ("اختياري", "حر"))}
                       for group in plan["credit_groups"]],
        course_count=plan["course_rows"], course_coverage=plan["course_coverage"], is_partial=partial,
        coverage_limitations=limitations, document_id=plan["document_id"], source_locator=plan["source_locator"],
    )


def programs(index: RetrievalIndex) -> list[ProgramEntry]:
    result = []
    for pid, (_, version, _, _) in TARGETS.items():
        plan = selected_plan(index, pid, version)
        result.append(ProgramEntry(program_id=pid, program_name_ar=plan["program_name_ar"],
                                   major_code=plan["major_code"], faculty_name_ar=plan.get("faculty_name_ar"),
                                   plans=[plan_summary(plan)]))
    return result


def courses(index: RetrievalIndex, program_id: str, plan_version: str) -> list[CourseEntry]:
    selected_plan(index, program_id, plan_version)
    return [CourseEntry(**{**row, "requirement_group_ar": row["requirement_group_ar"].strip()})
            for row in index.courses if row["program_id"] == program_id and row["plan_version"] == plan_version]


def validate_context(index: RetrievalIndex, context: AcademicContext) -> None:
    selected_plan(index, context.program_id, context.plan_version)
    allowed = {row["course_code"] for row in index.courses
               if row["program_id"] == context.program_id and row["plan_version"] == context.plan_version}
    if not set(context.completed_course_codes) <= allowed:
        raise ValueError("Unknown completed course for selected plan")
