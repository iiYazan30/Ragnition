// Request/response fields follow ../../../contracts/api-v1.md.
export type ProgramId = 'computer_engineering' | 'medicine' | 'physical_education' | 'vehicle_engineering'

export interface AcademicContext {
  program_id: ProgramId
  plan_version: string
  completed_course_codes: string[]
  user_declared_completed_credits?: number
}

export interface CreditGroup {
  name_ar: string
  required_credits: number
  is_elective: boolean
}

export interface SourceLocator {
  page: number | null
  section: string
  article?: string | null
  course_code?: string | null
  major_code?: string | null
}

export interface PlanSummary {
  plan_version: string
  total_required_credits: number
  credit_groups: CreditGroup[]
  course_count: number
  course_coverage: string
  is_partial: boolean
  coverage_limitations: string[]
  document_id: string
  source_locator: SourceLocator
}

export interface ProgramEntry {
  program_id: ProgramId
  program_name_ar: string
  major_code: string
  faculty_name_ar: string | null
  plans: PlanSummary[]
}

export interface Course {
  course_code: string
  course_name_ar: string
  course_name_en: string | null
  credits: number
  requirement_group_ar: string
  document_id: string
  source_locator: SourceLocator
  prerequisite_status: string
  prerequisite_expression_raw: string | null
}

export interface PlanCoursesResponse {
  program_id: ProgramId
  plan: PlanSummary
  courses: Course[]
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface Citation {
  source_id: string
  document_id: string
  title: string
  page: number | null
  quote: string
  filename: string
  article?: string | null
}

export type ResponseStatus =
  | 'answered'
  | 'insufficient_evidence'
  | 'out_of_scope'
  | 'needs_clarification'

export interface ChatResponse {
  request_id: string
  status: ResponseStatus
  answer: string
  citations: Citation[]
  latency_ms: number
}

export interface HealthResponse {
  status: string
  index_ready: boolean
  llm_configured: boolean
  documents_count: number
  chunks_count: number
}
