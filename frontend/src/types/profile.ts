import type { ProgramId } from './api'

export interface StudentProfile {
  name: string
  registrationNumber: string
  programId?: ProgramId
  planVersion?: string
  // Preserve old local details without interpreting them as catalog identifiers.
  batch?: string
  college?: string
  major?: string
  completedHours: number | ''
}
