import type { AcademicContext, Course, PlanSummary } from '../types/api.ts'
import type { StudentProfile } from '../types/profile.ts'

export const PROFILE_KEY = 'student_profile'

export function readProfile(storage: Pick<Storage, 'getItem'> = localStorage): StudentProfile {
  const data = JSON.parse(storage.getItem(PROFILE_KEY) || '{}')
  return {
    ...(data && typeof data === 'object' && !Array.isArray(data) ? data : {}),
    name: typeof data?.name === 'string' ? data.name : '',
    registrationNumber: typeof data?.registrationNumber === 'string' ? data.registrationNumber : '',
    completedHours: typeof data?.completedHours === 'number' && Number.isFinite(data.completedHours)
      && data.completedHours >= 0 && data.completedHours <= 400 ? data.completedHours : '',
  }
}

export function completionKey(programId: string, planVersion: string): string {
  // The old demo key is deliberately never imported into a real plan.
  return `student_completed_courses:v2:${programId}:${planVersion}`
}

export function readCompletions(programId: string, planVersion: string, storage: Pick<Storage, 'getItem'> = localStorage): string[] {
  const data: unknown = JSON.parse(storage.getItem(completionKey(programId, planVersion)) || '[]')
  return Array.isArray(data) ? [...new Set(data.filter((code): code is string =>
    typeof code === 'string' && /^[0-9]{7,9}$/.test(code)))] : []
}

export function checklistTotals(courses: Course[], selected: string[], plan: PlanSummary) {
  const codes = new Set(selected)
  const unique = [...new Map(courses.map((course) => [course.course_code, course])).values()]
  const completed = unique.filter((course) => codes.has(course.course_code))
  const groups = plan.credit_groups.map((group) => {
    const selectedCredits = completed.filter((course) => course.requirement_group_ar.trim() === group.name_ar.trim())
      .reduce((sum, course) => sum + course.credits, 0)
    return { ...group, selectedCredits, countedCredits: Math.min(selectedCredits, group.required_credits) }
  })
  return {
    completedCodes: completed.map((course) => course.course_code),
    courseCount: completed.length,
    selectedCredits: completed.reduce((sum, course) => sum + course.credits, 0),
    countedCredits: groups.reduce((sum, group) => sum + group.countedCredits, 0),
    groups,
  }
}

export function profileContext(profile: StudentProfile | null, storage: Pick<Storage, 'getItem'> = localStorage): AcademicContext | undefined {
  if (!profile?.programId || !profile.planVersion) return undefined
  return {
    program_id: profile.programId,
    plan_version: profile.planVersion,
    completed_course_codes: readCompletions(profile.programId, profile.planVersion, storage),
    ...(profile.completedHours !== '' ? { user_declared_completed_credits: profile.completedHours } : {}),
  }
}
