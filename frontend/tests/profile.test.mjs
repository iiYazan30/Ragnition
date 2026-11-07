import assert from 'node:assert/strict'
import { test } from 'node:test'
import { checklistTotals, completionKey, profileContext, readCompletions, readProfile } from '../src/services/profile.ts'

const storage = () => {
  const values = new Map()
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }
}

test('migration preserves identity and manual credits without inferring a plan or importing demo completions', () => {
  const store = storage()
  store.setItem('student_profile', JSON.stringify({ name: 'اسم محلي', registrationNumber: '12112345',
    batch: '121', major: 'تخصص قديم', college: 'كلية قديمة', completedHours: 75 }))
  store.setItem('student_completed_courses', JSON.stringify([{ id: 1, code: 'COMP133', isCompleted: true }]))
  const profile = readProfile(store)
  assert.equal(profile.name, 'اسم محلي')
  assert.equal(profile.registrationNumber, '12112345')
  assert.equal(profile.completedHours, 75)
  assert.equal(profile.programId, undefined)
  assert.equal(profileContext(profile, store), undefined)
  assert.deepEqual(readCompletions('computer_engineering', '2021-1', store), [])
})

test('switching program or plan restores only that key, including across a reload', () => {
  const store = storage()
  const ce = completionKey('computer_engineering', '2021-1')
  const medicine = completionKey('medicine', '2025-1')
  store.setItem(ce, JSON.stringify(['10221115', '10221115', 'COMP133']))
  assert.deepEqual(readCompletions('medicine', '2025-1', store), [])
  store.setItem(medicine, JSON.stringify(['10231214']))
  assert.deepEqual(readCompletions('computer_engineering', '2021-1', store), ['10221115'])
  assert.deepEqual(readCompletions('medicine', '2025-1', store), ['10231214'])
  assert.deepEqual(readCompletions('computer_engineering', '2025-1', store), [])
  const context = profileContext({ name: 'PRIVATE', registrationNumber: 'PRIVATE', completedHours: 75,
    programId: 'computer_engineering', planVersion: '2021-1' }, store)
  assert.deepEqual(context, { program_id: 'computer_engineering', plan_version: '2021-1',
    completed_course_codes: ['10221115'], user_declared_completed_credits: 75 })
})

test('zero-credit courses add no credits; duplicate rows count once and elective contribution is capped', () => {
  const courses = [
    { course_code: '10000001', credits: 0, requirement_group_ar: 'إجباري' },
    { course_code: '10000002', credits: 3, requirement_group_ar: 'اختياري' },
    { course_code: '10000003', credits: 3, requirement_group_ar: 'اختياري' },
  ]
  const plan = { credit_groups: [{ name_ar: 'إجباري', required_credits: 0, is_elective: false },
    { name_ar: 'اختياري', required_credits: 3, is_elective: true }] }
  const totals = checklistTotals([...courses, courses[1]], ['10000001', '10000002', '10000002', '10000003', '99999999'], plan)
  assert.equal(totals.courseCount, 3)
  assert.equal(totals.selectedCredits, 6)
  assert.equal(totals.countedCredits, 3)
  assert.equal(totals.groups[1].selectedCredits, 6)
  assert.equal(totals.groups[1].countedCredits, 3)
  assert.deepEqual(totals.completedCodes, courses.map((course) => course.course_code))
})
