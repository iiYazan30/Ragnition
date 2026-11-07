import assert from 'node:assert/strict'
import { test } from 'node:test'
import { getDocumentUrl, getHealth, getPlanCourses, getPrograms, sendChatMessage } from '../src/services/api.ts'

const citation = {
  source_id: 'course-1', document_id: 'plan/2026', title: 'الخطة الدراسية',
  filename: 'plan.htm', page: null, article: 'مساق 10636', quote: 'متطلب سابق',
}
const answer = {
  request_id: 'request-1', status: 'answered', answer: 'الإجابة الفعلية',
  citations: [citation], latency_ms: 10,
}
const json = (body, status = 200, headers = {}) => new Response(JSON.stringify(body), { status, headers })

test('sends the question and at most eight previous messages within contract limits', async (t) => {
  const history = Array.from({ length: 12 }, (_, i) => ({
    role: i % 2 ? 'assistant' : 'user', content: `message-${i}`,
  }))
  history[11].content = 'x'.repeat(4100)
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    assert.equal(url, 'http://127.0.0.1:8000/api/chat')
    assert.equal(init.method, 'POST')
    assert.equal(init.headers['Content-Type'], 'application/json')
    const body = JSON.parse(init.body)
    assert.equal(body.question, 'السؤال الحالي')
    assert.equal(body.history.length, 8)
    assert.deepEqual(body.history[0], history[4])
    assert.equal(body.history[7].content.length, 4000)
    assert.equal(body.history.some((m) => m.content === body.question), false)
    return json(answer)
  })
  assert.deepEqual(await sendChatMessage('  السؤال الحالي  ', history), answer)
})

test('all response statuses and server citations are preserved', async (t) => {
  for (const status of ['answered', 'insufficient_evidence', 'out_of_scope', 'needs_clarification']) {
    const response = { ...answer, status, citations: status === 'answered' ? [citation] : [] }
    t.mock.method(globalThis, 'fetch', async () => json(response))
    assert.deepEqual(await sendChatMessage('سؤال'), response)
    t.mock.restoreAll()
  }
})

test('builds document_id links: HTML has no fake page and PDF retains its page', () => {
  assert.equal(getDocumentUrl('plan/2026'), 'http://127.0.0.1:8000/api/documents/plan%2F2026/file')
  assert.equal(getDocumentUrl('guide', 23), 'http://127.0.0.1:8000/api/documents/guide/file#page=23')
})

test('rejects blank and oversized questions without sending a request', async (t) => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => json(answer))
  await assert.rejects(sendChatMessage('   '), /2000/)
  await assert.rejects(sendChatMessage('x'.repeat(2001)), /2000/)
  assert.equal(fetch.mock.callCount(), 0)
})

test('ignores empty history content', async (t) => {
  t.mock.method(globalThis, 'fetch', async (_url, init) => {
    assert.deepEqual(JSON.parse(init.body).history, [{ role: 'user', content: 'سؤال سابق' }])
    return json(answer)
  })
  await sendChatMessage('سؤال', [{ role: 'assistant', content: ' ' }, { role: 'user', content: 'سؤال سابق' }])
})

test('HTTP errors explain rate limiting, unavailable knowledge, and upstream failures', async (t) => {
  for (const [status, headers, pattern] of [
    [429, { 'Retry-After': '15' }, /15 ثانية/],
    [429, {}, /رسالة الخادم/],
    [503, {}, /غير متاحة/],
    [504, {}, /مهلة/],
    [502, {}, /رسالة الخادم/],
  ]) {
    t.mock.method(globalThis, 'fetch', async () => json({ error: { message: 'رسالة الخادم' } }, status, headers))
    await assert.rejects(sendChatMessage('سؤال'), pattern)
    t.mock.restoreAll()
  }
})

test('network failures show a retryable connection error', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => { throw new TypeError('Failed to fetch') })
  await assert.rejects(sendChatMessage('سؤال'), /تعذّر الاتصال/)
})

test('aborts a stalled request after 60 seconds', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  t.mock.method(globalThis, 'fetch', (_url, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  }))
  const pending = assert.rejects(sendChatMessage('سؤال'), /انتهت مهلة الاتصال/)
  t.mock.timers.tick(60_000)
  await pending
})

test('rejects malformed responses and citations instead of breaking the UI', async (t) => {
  for (const body of [null, { ...answer, status: 'unknown' }, { ...answer, citations: [null] },
    { ...answer, citations: [{ ...citation, page: 0 }] }, { ...answer, latency_ms: -1 }]) {
    t.mock.method(globalThis, 'fetch', async () => json(body))
    await assert.rejects(sendChatMessage('سؤال'), /رد غير صالح/)
    t.mock.restoreAll()
  }
})

test('reads health from the real health endpoint without hiding degraded status', async (t) => {
  const health = { status: 'degraded', index_ready: true, llm_configured: true, documents_count: 5, chunks_count: 545 }
  t.mock.method(globalThis, 'fetch', async (url) => {
    assert.equal(url, 'http://127.0.0.1:8000/api/health')
    return json(health)
  })
  assert.deepEqual(await getHealth(), health)
})

test('degraded health and conflicting history preserve the explicit plan-total request and HTML citation', async (t) => {
  const question = 'كم مجموع ساعات الحاسوب خطة 2021-1؟'
  const history = [{ role: 'user', content: 'أنا في الطب خطة 2025-1' }]
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    if (url.endsWith('/api/health')) {
      return json({ status: 'degraded', index_ready: true, llm_configured: true, documents_count: 5, chunks_count: 545 })
    }
    assert.deepEqual(JSON.parse(init.body), { question, history })
    return json(answer)
  })
  assert.equal((await getHealth()).index_ready, true)
  const response = await sendChatMessage(question, history)
  assert.equal(response.status, 'answered')
  assert.equal(response.citations[0].page, null)
  assert.equal(getDocumentUrl(response.citations[0].document_id, null).includes('#page='), false)
})

test('a provider 429 rejects as an error even when its body contains a misleading response status', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => json({
    status: 'insufficient_evidence',
    error: { code: 'LLM_RATE_LIMIT', message: 'طلبات كثيرة', request_id: 'quota-request' },
  }, 429, { 'Retry-After': '60' }))
  await assert.rejects(sendChatMessage('كم مجموع ساعات الحاسوب خطة 2021-1؟'), (error) => {
    assert.ok(error instanceof Error)
    assert.match(error.message, /60 ثانية/)
    assert.equal(error.status, undefined)
    return true
  })
})

test('serializes only typed academic context, never local identity or legacy demo fields', async (t) => {
  const context = { program_id: 'computer_engineering', plan_version: '2021-1',
    completed_course_codes: ['10032100', '10032100'], user_declared_completed_credits: 12,
    name: 'PRIVATE_NAME', registrationNumber: 'PRIVATE_REGISTRATION', major: 'OLD_MAJOR' }
  t.mock.method(globalThis, 'fetch', async (_url, init) => {
    assert.deepEqual(JSON.parse(init.body).academic_context, {
      program_id: context.program_id, plan_version: context.plan_version,
      completed_course_codes: ['10032100'], user_declared_completed_credits: 12,
    })
    assert.equal(/PRIVATE_|OLD_MAJOR/.test(init.body), false)
    return json(answer)
  })
  await sendChatMessage('كم مجموع الساعات؟', [], context)
})

test('unavailable and malformed catalogs stay errors, with no demo fallback', async (t) => {
  for (const load of [() => getPrograms(), () => getPlanCourses('computer_engineering', '2021-1')]) {
    t.mock.method(globalThis, 'fetch', async () => json({ error: { code: 'CATALOG_UNAVAILABLE' } }, 503))
    await assert.rejects(load(), /كتالوج.*غير متاح/)
    t.mock.restoreAll()
    t.mock.method(globalThis, 'fetch', async () => json({ programs: [], courses: [] }))
    await assert.rejects(load(), /غير صالح/)
    t.mock.restoreAll()
  }
})
