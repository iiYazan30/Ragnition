import React, { useEffect, useRef, useState } from 'react'
import { BookOpen, CheckSquare, GraduationCap, Save, User, X } from 'lucide-react'
import type { Course, PlanCoursesResponse, ProgramEntry } from '../types/api'
import type { StudentProfile } from '../types/profile'
import { getDocumentUrl, getPlanCourses, getPrograms } from '../services/api'
import { checklistTotals, completionKey, PROFILE_KEY, readCompletions, readProfile } from '../services/profile'

interface ProfileModalProps {
  isOpen: boolean
  onClose: () => void
  onProfileSaved?: (profile: StudentProfile) => void
}

const fieldClass = 'w-full px-3 py-2.5 rounded-xl border border-gray-300 bg-gray-50 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60'
const emptyProfile: StudentProfile = { name: '', registrationNumber: '', completedHours: '' }

export const ProfileModal: React.FC<ProfileModalProps> = ({ isOpen, onClose, onProfileSaved }) => {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [tab, setTab] = useState<'profile' | 'plan'>('profile')
  const [profile, setProfile] = useState<StudentProfile>(emptyProfile)
  const [programs, setPrograms] = useState<ProgramEntry[]>([])
  const [catalogError, setCatalogError] = useState('')
  const [catalogLoading, setCatalogLoading] = useState(false)
  const [courseData, setCourseData] = useState<PlanCoursesResponse | null>(null)
  const [courseError, setCourseError] = useState('')
  const [storageError, setStorageError] = useState('')
  const [completed, setCompleted] = useState<string[]>([])
  const [completionScope, setCompletionScope] = useState('')
  const [search, setSearch] = useState('')
  const [retry, setRetry] = useState(0)
  const program = programs.find((item) => item.program_id === profile.programId)
  const data = courseData && courseData.program_id === profile.programId && courseData.plan.plan_version === profile.planVersion ? courseData : null
  const activeScope = profile.programId && profile.planVersion ? completionKey(profile.programId, profile.planVersion) : ''
  const selectedCodes = completionScope === activeScope ? completed : []
  const totals = data ? checklistTotals(data.courses, selectedCodes, data.plan) : null

  useEffect(() => {
    if (!isOpen) return
    dialogRef.current?.showModal()
    setStorageError('')
    try { setProfile(readProfile()) }
    catch { setProfile(emptyProfile); setStorageError('تعذر قراءة الملف المحلي. يمكنك إعادة إدخال بياناتك وحفظها.') }
  }, [isOpen])

  useEffect(() => {
    if (!isOpen) return
    let active = true
    setCatalogLoading(true)
    setCatalogError('')
    getPrograms().then((items) => {
      if (!active) return
      setPrograms(items)
      setProfile((previous) => {
        const selected = items.find((item) => item.program_id === previous.programId)
        return selected?.plans.length === 1 ? { ...previous, planVersion: selected.plans[0].plan_version } : previous
      })
    }).catch((error) => {
      if (active) { setPrograms([]); setCatalogError(error instanceof Error ? error.message : 'تعذر تحميل البرامج.') }
    }).finally(() => { if (active) setCatalogLoading(false) })
    return () => { active = false }
  }, [isOpen, retry])

  useEffect(() => {
    if (!isOpen) return
    let active = true
    setCourseData(null)
    setCourseError('')
    setCompleted([])
    setCompletionScope('')
    setSearch('')
    if (!profile.programId || !profile.planVersion) return
    setCompletionScope(completionKey(profile.programId, profile.planVersion))
    try {
      setCompleted(readCompletions(profile.programId, profile.planVersion))
    }
    catch { setStorageError('تعذر قراءة المقررات المحفوظة. لم تُنقل اختيارات من خطة أخرى.') }
    getPlanCourses(profile.programId, profile.planVersion).then((result) => {
      if (active) setCourseData(result)
    }).catch((error) => {
      if (active) setCourseError(error instanceof Error ? error.message : 'تعذر تحميل المقررات.')
    })
    return () => { active = false }
  }, [isOpen, profile.programId, profile.planVersion, retry])

  const saveProfile = (event: React.FormEvent) => {
    event.preventDefault()
    if (profile.programId && (!profile.planVersion || (programs.length > 0 && !program))) {
      setStorageError('اختر تخصصاً وخطة من الكتالوج المتاح قبل الحفظ.')
      return
    }
    const saved = { ...profile, name: profile.name.trim(), registrationNumber: profile.registrationNumber.trim() }
    try {
      localStorage.setItem(PROFILE_KEY, JSON.stringify(saved))
      onProfileSaved?.(saved)
      onClose()
    } catch { setStorageError('تعذر الحفظ في المتصفح. تحقق من إتاحة التخزين المحلي وأعد المحاولة.') }
  }

  const toggleCourse = (course: Course) => {
    if (!data || !totals || !profile.programId || !profile.planVersion || completionScope !== activeScope) return
    const next = totals.completedCodes.includes(course.course_code)
      ? totals.completedCodes.filter((code) => code !== course.course_code)
      : [...totals.completedCodes, course.course_code]
    try {
      localStorage.setItem(completionKey(profile.programId, profile.planVersion), JSON.stringify(next))
      setCompleted(next)
      setStorageError('')
    } catch { setStorageError('تعذر حفظ اختيار المقرر؛ لم تتغير الاختيارات المحفوظة.') }
  }

  if (!isOpen) return null
  const query = search.trim().normalize('NFKC').toLocaleLowerCase()
  const matches = (course: Course) => `${course.course_code} ${course.course_name_ar} ${course.course_name_en || ''}`.normalize('NFKC').toLocaleLowerCase().includes(query)

  return (
    <dialog ref={dialogRef} onCancel={(event) => { event.preventDefault(); onClose() }} aria-labelledby="profile-title"
      className="p-0 m-auto w-[calc(100%_-_1.5rem)] max-w-2xl max-h-[90vh] rounded-2xl border border-gray-200 shadow-2xl backdrop:bg-black/40" dir="rtl">
      <div className="flex flex-col max-h-[90vh] bg-white text-gray-800">
        <header className="flex items-center justify-between gap-3 px-5 py-4 bg-gradient-to-l from-blue-600 to-blue-700 text-white shrink-0">
          <div className="flex items-center gap-3"><GraduationCap className="w-6 h-6" /><div>
            <h2 id="profile-title" className="font-bold">الملف الأكاديمي وخطة الطالب</h2>
            <p className="text-xs text-blue-100 mt-1">بياناتك محلية، والمقررات من المصادر المتاحة</p>
          </div></div>
          <button type="button" onClick={onClose} aria-label="إغلاق الملف الأكاديمي" className="p-2 rounded-lg hover:bg-white/15"><X className="w-5 h-5" /></button>
        </header>
        <div className="flex border-b bg-gray-50 px-4 shrink-0" role="tablist" aria-label="الملف والخطة" onKeyDown={(event) => {
          if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
          event.preventDefault()
          const next = tab === 'profile' ? 'plan' : 'profile'
          setTab(next)
          document.getElementById(`tab-${next}`)?.focus()
        }}>
          {(['profile', 'plan'] as const).map((value) => (
            <button key={value} type="button" role="tab" tabIndex={tab === value ? 0 : -1} aria-selected={tab === value} aria-controls={`panel-${value}`} id={`tab-${value}`}
              onClick={() => setTab(value)} className={`flex items-center gap-2 px-4 py-3 text-sm font-semibold border-b-2 ${tab === value ? 'border-blue-600 text-blue-700' : 'border-transparent text-gray-600'}`}>
              {value === 'profile' ? <User className="w-4 h-4" /> : <CheckSquare className="w-4 h-4" />}
              {value === 'profile' ? 'بيانات الطالب' : 'خطة الطالب'}
            </button>
          ))}
        </div>
        <div className="overflow-y-auto p-5 sm:p-6 space-y-4">
          {storageError && <p role="alert" className="text-sm bg-red-50 text-red-800 border border-red-200 p-3 rounded-xl">{storageError}</p>}
          {tab === 'profile' ? (
            <form id="panel-profile" role="tabpanel" aria-labelledby="tab-profile" onSubmit={saveProfile} className="space-y-4">
              <div><label htmlFor="student-name" className="block text-sm font-semibold mb-1.5">الاسم الكامل</label>
                <input id="student-name" value={profile.name} onChange={(event) => setProfile({ ...profile, name: event.target.value })} autoComplete="name" className={fieldClass} /></div>
              <div><label htmlFor="student-registration" className="block text-sm font-semibold mb-1.5">رقم التسجيل</label>
                <input id="student-registration" value={profile.registrationNumber} onChange={(event) => setProfile({ ...profile, registrationNumber: event.target.value })} className={`${fieldClass} font-mono`} dir="ltr" />
                <p className="text-xs text-gray-500 mt-1">لا نستنتج الخطة أو الدفعة من رقم التسجيل. الاسم والرقم لا يُرسلان إلى خدمة الإجابة.</p></div>
              <div><label htmlFor="student-program" className="block text-sm font-semibold mb-1.5">التخصص</label>
                <select id="student-program" value={profile.programId || ''} disabled={catalogLoading || !!catalogError} className={fieldClass}
                  onChange={(event) => {
                    const selected = programs.find((item) => item.program_id === event.target.value)
                    setProfile({ ...profile, programId: selected?.program_id, planVersion: selected?.plans.length === 1 ? selected.plans[0].plan_version : undefined })
                  }}>
                  <option value="">اختر التخصص من الكتالوج</option>
                  {programs.map((item) => <option key={item.program_id} value={item.program_id}>{item.program_name_ar} — {item.major_code}</option>)}
                </select>
                {catalogLoading && <p role="status" className="text-sm mt-2 text-gray-600">جارٍ تحميل البرامج...</p>}
                {catalogError && <div role="alert" className="mt-2 text-sm text-red-700">{catalogError} <button type="button" onClick={() => setRetry((value) => value + 1)} className="underline font-semibold">إعادة المحاولة</button></div>}
              </div>
              {program && <div className="rounded-xl bg-blue-50 border border-blue-100 p-3 space-y-2 text-sm">
                {program.plans.length === 1 ? <p>نسخة الخطة: <strong dir="ltr">{profile.planVersion}</strong> — النسخة المتاحة لهذا التخصص</p> : <>
                  <label htmlFor="student-plan">نسخة الخطة</label><select id="student-plan" className={fieldClass} value={profile.planVersion || ''} onChange={(event) => setProfile({ ...profile, planVersion: event.target.value })}>
                    <option value="">اختر نسخة الخطة</option>{program.plans.map((plan) => <option key={plan.plan_version} value={plan.plan_version}>{plan.plan_version}</option>)}
                  </select></>}
                {program.faculty_name_ar && <p>الكلية: {program.faculty_name_ar}</p>}
                {program.plans.find((plan) => plan.plan_version === profile.planVersion)?.coverage_limitations.map((note) => <p key={note} className="text-xs leading-relaxed">{note}</p>)}
              </div>}
              <div><label htmlFor="student-manual-credits" className="block text-sm font-semibold mb-1.5">ساعات منجزة تصرّح بها يدوياً (اختياري)</label>
                <input id="student-manual-credits" type="number" min="0" max="400" step="any" value={profile.completedHours} className={fieldClass}
                  onChange={(event) => setProfile({ ...profile, completedHours: event.target.value === '' ? '' : Number(event.target.value) })} />
                <p className="text-xs text-gray-500 mt-1">قيمة مستقلة عن مجموع المقررات المحددة، وليست كشف علامات رسمياً.</p></div>
              <div className="flex items-center justify-end gap-3 pt-3 border-t">
                <button type="button" onClick={onClose} className="px-4 py-2 text-sm border rounded-xl">إلغاء</button>
                <button type="submit" className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-semibold"><Save className="w-4 h-4" />حفظ البيانات</button>
              </div>
            </form>
          ) : (
            <section id="panel-plan" role="tabpanel" aria-labelledby="tab-plan" className="space-y-4">
              {!profile.programId || !profile.planVersion ? <p className="text-sm text-gray-600">اختر التخصص والخطة من تبويب بيانات الطالب لعرض المقررات الحقيقية.</p>
                : courseError ? <div role="alert" className="text-sm p-3 border border-red-200 bg-red-50 rounded-xl">{courseError} <button type="button" onClick={() => setRetry((value) => value + 1)} className="underline">إعادة المحاولة</button></div>
                : !data || !totals ? <p role="status" className="text-sm text-gray-600">جارٍ تحميل مقررات الخطة...</p> : <>
                  <div className="bg-blue-50 border border-blue-100 rounded-2xl p-4 space-y-2">
                    <h3 className="font-bold text-sm">{program?.program_name_ar} — خطة <span dir="ltr">{data.plan.plan_version}</span></h3>
                    <p className="text-sm">المقررات المحددة: <strong>{totals.courseCount}</strong>، مجموع ساعاتها: <strong>{totals.selectedCredits}</strong></p>
                    <p className="text-xs text-gray-600">الاحتساب الاسترشادي بعد سقوف المجموعات: {totals.countedCredits} ساعة. إجمالي المصدر: {data.plan.total_required_credits} ساعة.</p>
                    {profile.completedHours !== '' && <p className="text-xs text-gray-600">الساعات المصرح بها يدوياً، بشكل مستقل: {profile.completedHours}</p>}
                    {data.plan.coverage_limitations.map((note) => <p key={note} className={`text-xs leading-relaxed ${data.plan.is_partial ? 'text-amber-900' : 'text-gray-600'}`}>{note}</p>)}
                    <p className="text-xs text-gray-600">الاختيارات تصريح شخصي وليست إثبات اجتياز أو أهلية تسجيل. لا يلزم إكمال جميع البدائل الاختيارية.</p>
                  </div>
                  <div><label htmlFor="course-search" className="text-sm font-semibold block mb-1.5">ابحث برمز المقرر أو اسمه</label>
                    <input id="course-search" type="search" value={search} onChange={(event) => setSearch(event.target.value)} className={fieldClass} /></div>
                  {!data.courses.some(matches) && <p role="status" className="text-sm text-gray-600">لا توجد مقررات مطابقة للبحث.</p>}
                  {totals.groups.map((group) => {
                    const rows = data.courses.filter((course) => course.requirement_group_ar === group.name_ar)
                    const visible = rows.filter(matches)
                    if (query && !visible.length) return null
                    return <fieldset key={group.name_ar} className="border border-gray-200 rounded-xl p-3 space-y-2">
                      <legend className="px-1 text-sm font-bold">{group.name_ar}</legend>
                      <p className="text-xs text-gray-600">المحدد {group.selectedCredits} ساعة؛ المحتسب استرشادياً {group.countedCredits} من {group.required_credits} مطلوبة{group.is_elective ? ' — بدائل، وليست جميعها مطلوبة' : ''}.</p>
                      {!rows.length && <p className="text-xs text-amber-900">خيارات هذه المجموعة غير متوفرة في المصادر الحالية.</p>}
                      {visible.map((course) => <div key={course.course_code} className={`p-3 rounded-xl border ${selectedCodes.includes(course.course_code) ? 'bg-green-50 border-green-200' : 'bg-white border-gray-200'}`}>
                        <label className="flex items-start gap-3 cursor-pointer">
                          <input type="checkbox" checked={selectedCodes.includes(course.course_code)} onChange={() => toggleCourse(course)} className="mt-1 w-4 h-4 accent-blue-600 shrink-0" />
                          <span className="flex-1 min-w-0 text-sm"><span className="font-semibold">{course.course_name_ar}</span><span className="block mt-1 text-xs text-gray-600"><span className="font-mono" dir="ltr">{course.course_code}</span> · {course.credits} ساعة</span></span>
                        </label>
                        <details className="mt-2 text-xs text-gray-600">
                          <summary className="cursor-pointer">المتطلبات والمصدر</summary>
                          <p className="mt-2 leading-relaxed">{course.prerequisite_expression_raw || (course.prerequisite_status === 'not_provided_for_this_plan' ? 'المتطلبات السابقة الرسمية غير متوفرة لهذه الخطة.' : 'لم تُذكر متطلبات في صف المصدر؛ لا يعني ذلك تأكيد عدم وجود متطلب.')}</p>
                          <a href={getDocumentUrl(course.document_id, course.source_locator.page)} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-blue-700 underline mt-2"><BookOpen className="w-3 h-3" />فتح المصدر{course.source_locator.page !== null ? ` — صفحة ${course.source_locator.page}` : ''}</a>
                        </details>
                      </div>)}
                    </fieldset>
                  })}
                  <p className="text-xs text-gray-500">تُحفظ علامات الإنجاز فوراً لهذا التخصص ونسخة الخطة في هذا المتصفح. احفظ بيانات الطالب لاعتماد تخصص جديد في المحادثة.</p>
                </>}
            </section>
          )}
        </div>
      </div>
    </dialog>
  )
}
