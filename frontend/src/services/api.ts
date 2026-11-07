import type { AcademicContext, ChatMessage, ChatResponse, Citation, Course, HealthResponse, PlanCoursesResponse, PlanSummary, ProgramEntry } from '../types/api.ts'

// Contract: ../../../contracts/api-v1.md; the base URL is the server origin, without /api.
const API_BASE_URL = (import.meta.env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000')
  .trim().replace(/\/+$/, '')

export function getDocumentUrl(documentId: string, page: number | null = null): string {
  return `${API_BASE_URL}/api/documents/${encodeURIComponent(documentId)}/file${
    page !== null ? `#page=${page}` : ''
  }`
}

async function requestJson(path: string, init: RequestInit = {}, timeoutMs = 60_000): Promise<unknown> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, { ...init, signal: controller.signal })
    const body = await response.json().catch(() => null)
    if (controller.signal.aborted) throw new Error('timeout')
    if (!response.ok) {
      if (response.status === 429) {
        const retryAfter = response.headers.get('Retry-After')
        const seconds = retryAfter && /^\d+$/.test(retryAfter) ? Number(retryAfter) : null
        const message = typeof body?.error?.message === 'string' ? body.error.message : 'طلبات كثيرة. راجع الحصة المتاحة.'
        throw new Error(`${message}${seconds !== null ? ` انتظر ${seconds} ثانية ثم أعد المحاولة.` : ''}`)
      }
      if (response.status === 503) {
        if (body?.error?.code === 'CATALOG_UNAVAILABLE') throw new Error('كتالوج البرامج والمقررات غير متاح حالياً. أعد المحاولة لاحقاً.')
        throw new Error('خدمة الإجابة أو مصادر المعرفة غير متاحة حالياً. أعد المحاولة لاحقاً.')
      }
      if (response.status === 504) {
        throw new Error('انتهت مهلة إعداد الإجابة في الخادم. أعد المحاولة.')
      }
      const message = body?.error?.message
      throw new Error(typeof message === 'string' ? message : 'تعذّر معالجة الطلب. أعد المحاولة لاحقاً.')
    }
    return body
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error('انتهت مهلة الاتصال بالخادم. أعد المحاولة.')
    }
    if (error instanceof TypeError) {
      throw new Error('تعذّر الاتصال بالخادم. تحقق من اتصالك ومن تشغيل الخدمة ثم أعد المحاولة.')
    }
    throw error
  } finally {
    clearTimeout(timeout)
  }
}

function isCitation(value: unknown): value is Citation {
  if (!value || typeof value !== 'object') return false
  const c = value as Record<string, unknown>
  return ['source_id', 'document_id', 'title', 'filename', 'quote'].every(
    (key) => typeof c[key] === 'string'
  ) && (c.page === null || (Number.isInteger(c.page) && Number(c.page) >= 1))
    && (c.article === undefined || c.article === null || typeof c.article === 'string')
}

export async function sendChatMessage(
  question: string,
  history: ChatMessage[] = [],
  academicContext?: AcademicContext,
): Promise<ChatResponse> {
  const trimmed = question.trim()
  if (!trimmed || trimmed.length > 2000) {
    throw new Error('اكتب سؤالاً من حرف واحد إلى 2000 حرف.')
  }
  const body = await requestJson('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question: trimmed,
      academic_context: academicContext ? {
        program_id: academicContext.program_id,
        plan_version: academicContext.plan_version,
        completed_course_codes: [...new Set(academicContext.completed_course_codes)],
        ...(academicContext.user_declared_completed_credits !== undefined
          ? { user_declared_completed_credits: academicContext.user_declared_completed_credits } : {}),
      } : undefined,
      history: history
        .filter((m) => (m.role === 'user' || m.role === 'assistant') && m.content.trim())
        .slice(-8)
        .map(({ role, content }) => ({ role, content: content.slice(0, 4000) })),
    }),
  })
  const result = body as ChatResponse | null
  if (!result || typeof result.request_id !== 'string' || typeof result.answer !== 'string'
    || !['answered', 'insufficient_evidence', 'out_of_scope', 'needs_clarification'].includes(result.status)
    || !Array.isArray(result.citations) || !result.citations.every(isCitation)
    || !Number.isInteger(result.latency_ms) || result.latency_ms < 0) {
    throw new Error('وصل رد غير صالح من الخادم. أعد المحاولة لاحقاً.')
  }
  return result
}

export async function getHealth(): Promise<HealthResponse> {
  const body = await requestJson('/api/health', {}, 10_000) as HealthResponse | null
  if (!body || typeof body.status !== 'string' || typeof body.index_ready !== 'boolean'
    || typeof body.llm_configured !== 'boolean') {
    throw new Error('تعذّر التحقق من حالة الخدمة.')
  }
  return body
}

function isPlan(value: unknown): value is PlanSummary {
  if (!value || typeof value !== 'object') return false
  const plan = value as PlanSummary
  return typeof plan.plan_version === 'string' && Number.isFinite(plan.total_required_credits)
    && plan.total_required_credits >= 0 && typeof plan.is_partial === 'boolean'
    && typeof plan.document_id === 'string' && typeof plan.course_coverage === 'string'
    && Number.isInteger(plan.course_count) && plan.course_count >= 0
    && Array.isArray(plan.coverage_limitations) && plan.coverage_limitations.every((text) => typeof text === 'string')
    && Array.isArray(plan.credit_groups) && plan.credit_groups.every((group) => group
      && typeof group.name_ar === 'string' && Number.isFinite(group.required_credits)
      && group.required_credits >= 0 && typeof group.is_elective === 'boolean')
}

export async function getPrograms(): Promise<ProgramEntry[]> {
  const body = await requestJson('/api/programs', {}, 10_000) as { programs?: ProgramEntry[] } | null
  if (!Array.isArray(body?.programs) || !body.programs.length || !body.programs.every((program) => program
    && typeof program.program_id === 'string' && typeof program.program_name_ar === 'string'
    && (program.faculty_name_ar === null || typeof program.faculty_name_ar === 'string')
    && typeof program.major_code === 'string' && Array.isArray(program.plans)
    && program.plans.length > 0 && program.plans.every(isPlan))) {
    throw new Error('وصل كتالوج برامج غير صالح. أعد المحاولة لاحقاً.')
  }
  return body.programs
}

export async function getPlanCourses(programId: string, planVersion: string): Promise<PlanCoursesResponse> {
  const body = await requestJson(`/api/programs/${encodeURIComponent(programId)}/plans/${encodeURIComponent(planVersion)}/courses`, {}, 10_000) as PlanCoursesResponse | null
  const isCourse = (course: Course) => course && typeof course.course_code === 'string' && /^[0-9]{7,9}$/.test(course.course_code)
    && typeof course.course_name_ar === 'string' && typeof course.requirement_group_ar === 'string'
    && Number.isFinite(course.credits) && course.credits >= 0 && typeof course.prerequisite_status === 'string'
    && (course.prerequisite_expression_raw === null || typeof course.prerequisite_expression_raw === 'string')
    && typeof course.document_id === 'string' && course.source_locator
    && (course.source_locator.page === null || (Number.isInteger(course.source_locator.page) && course.source_locator.page >= 1))
  if (!body || body.program_id !== programId || !isPlan(body.plan) || body.plan.plan_version !== planVersion
    || !Array.isArray(body.courses) || !body.courses.every(isCourse)
    || body.courses.length !== body.plan.course_count
    || !body.courses.every((course) => body.plan.credit_groups.some((group) => group.name_ar === course.requirement_group_ar))
    || new Set(body.courses.map((course) => course.course_code)).size !== body.courses.length) {
    throw new Error('وصلت قائمة مقررات غير صالحة. أعد المحاولة لاحقاً.')
  }
  return body
}
