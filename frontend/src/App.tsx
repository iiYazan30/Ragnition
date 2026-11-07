import React, { useState, useEffect, useRef } from 'react'
import {
  GraduationCap,
  Send,
  Sparkles,
  BookOpen,
  Trash2,
  HardDrive,
  User,
  PanelRight,
} from 'lucide-react'
import { getHealth, sendChatMessage } from './services/api'
import { profileContext, readProfile } from './services/profile'
import type { ChatMessage } from './types/api'
import type { StudentProfile } from './types/profile'
import type { UIMessage, ChatSession } from './types/chat'
import { MessageBubble } from './components/MessageBubble'
import { ProfileModal } from './components/ProfileModal'
import { Sidebar } from './components/Sidebar'

const SESSIONS_STORAGE_KEY = 'academic_chat_sessions'
const connectionStates = {
  checking: { label: 'جارٍ التحقق', style: 'bg-gray-50 border-gray-200 text-gray-600', dot: 'bg-gray-400' },
  ready: { label: 'متصل', style: 'bg-green-50 border-green-200 text-green-700', dot: 'bg-green-500' },
  degraded: { label: 'خدمة محدودة', style: 'bg-amber-50 border-amber-200 text-amber-800', dot: 'bg-amber-500' },
  knowledge_unavailable: { label: 'المعرفة غير متاحة', style: 'bg-amber-50 border-amber-200 text-amber-800', dot: 'bg-amber-500' },
  unavailable: { label: 'غير متصل', style: 'bg-red-50 border-red-200 text-red-700', dot: 'bg-red-500' },
}

function createDefaultSession(): ChatSession {
  return {
    id: `session-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
    title: 'محادثة جديدة',
    summary: '',
    messages: [],
    createdAt: Date.now(),
  }
}

export default function App() {
  // 1. Refactor State: Multiple sessions with persistence
  const [sessions, setSessions] = useState<ChatSession[]>(() => {
    try {
      const saved = localStorage.getItem(SESSIONS_STORAGE_KEY)
      if (saved) {
        const parsed = JSON.parse(saved)
        if (Array.isArray(parsed) && parsed.length > 0) {
          return parsed
        }
      }
      // Migration from previous single-session storage if present
      const oldSaved = localStorage.getItem('academic_advisor_chat_messages')
      if (oldSaved) {
        const oldMessages: UIMessage[] = JSON.parse(oldSaved)
        if (Array.isArray(oldMessages) && oldMessages.length > 0) {
          const firstMsg = oldMessages.find((m) => m.role === 'user')
          return [
            {
              id: `session-${Date.now()}`,
              title: firstMsg ? `${firstMsg.content.slice(0, 24)}...` : 'محادثة سابقة',
              summary: firstMsg
                ? `ملخص المحادثة السابقة: الطالب كان يستفسر عن: ${firstMsg.content}`
                : '',
              messages: oldMessages,
              createdAt: Date.now(),
            },
          ]
        }
      }
    } catch (err) {
      console.error('Failed to load chat sessions from localStorage:', err)
    }
    return [createDefaultSession()]
  })

  const [activeSessionId, setActiveSessionId] = useState<string>(() => {
    return sessions[0]?.id || `session-${Date.now()}`
  })

  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const pendingSessionRef = useRef<string | null>(null)
  const [connection, setConnection] = useState<keyof typeof connectionStates>('checking')
  const connectionState = connectionStates[connection]
  const [isProfileOpen, setIsProfileOpen] = useState(false)
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)

  const [studentProfile, setStudentProfile] = useState<StudentProfile | null>(() => {
    try {
      return readProfile()
    } catch {
      return null
    }
  })

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    let mounted = true
    const checkHealth = async () => {
      try {
        const health = await getHealth()
        if (mounted) setConnection(!health.index_ready ? 'knowledge_unavailable'
          : !health.llm_configured || health.status !== 'ok' ? 'degraded' : 'ready')
      } catch {
        if (mounted) setConnection('unavailable')
      }
    }
    void checkHealth()
    const interval = setInterval(checkHealth, 30_000)
    return () => { mounted = false; clearInterval(interval) }
  }, [])

  // Save sessions to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(SESSIONS_STORAGE_KEY, JSON.stringify(sessions))
    } catch (err) {
      console.error('Failed to save sessions to localStorage:', err)
    }
  }, [sessions])

  // Get active session and its messages
  const activeSession =
    sessions.find((s) => s.id === activeSessionId) || sessions[0] || createDefaultSession()
  const messages = activeSession.messages

  // Auto-scroll to bottom whenever messages or loading state changes
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  // Handle textarea auto-resize
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value)
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 144)}px`
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      handleSubmit()
    }
  }

  // 3. New Chat Logic & Memory Summarization
  const handleNewChat = () => {
    const newSession = createDefaultSession()

    setSessions((prevSessions) => {
      const updated = prevSessions.map((s) => {
        if (s.id === activeSessionId) {
          const firstUserMessage = s.messages.find((m) => m.role === 'user')
          const generatedSummary = firstUserMessage
            ? `ملخص المحادثة السابقة: الطالب كان يستفسر عن: ${firstUserMessage.content}`
            : s.summary

          const updatedTitle =
            s.title === 'محادثة جديدة' && firstUserMessage
              ? `${firstUserMessage.content.slice(0, 24)}...`
              : s.title

          return {
            ...s,
            summary: generatedSummary,
            title: updatedTitle,
          }
        }
        return s
      })

      return [newSession, ...updated]
    })

    setActiveSessionId(newSession.id)
  }

  // Delete an individual session
  const handleDeleteSession = (sessionIdToDelete: string) => {
    if (pendingSessionRef.current === sessionIdToDelete) return
    if (sessions.length <= 1) {
      // If only one session left, reset it
      setSessions([createDefaultSession()])
      return
    }
    const remaining = sessions.filter((s) => s.id !== sessionIdToDelete)
    setSessions(remaining)
    if (activeSessionId === sessionIdToDelete) {
      setActiveSessionId(remaining[0].id)
    }
  }

  // Clear current active chat messages
  const handleClearActiveSession = () => {
    if (pendingSessionRef.current === activeSessionId) return
    setSessions((prev) =>
      prev.map((s) =>
        s.id === activeSessionId
          ? { ...s, messages: [], summary: '', title: 'محادثة جديدة' }
          : s
      )
    )
  }

  // Send only this session's actual previous messages.
  const sendMessageWithQuery = async (queryText: string) => {
    const trimmed = queryText.trim()
    if (!trimmed || trimmed.length > 2000 || pendingSessionRef.current) return
    pendingSessionRef.current = activeSessionId

    const userMessageId = `user-${Date.now()}`
    const timeString = new Date().toLocaleTimeString('ar-SA', {
      hour: '2-digit',
      minute: '2-digit',
    })

    const newUserMessage: UIMessage = {
      id: userMessageId,
      role: 'user',
      content: trimmed,
      timestamp: timeString,
    }

    // Format history per API Contract (valid previous messages, { role, content }, max 8)
    const history: ChatMessage[] = activeSession.messages
      .filter((m) => !m.isError && Boolean(m.content?.trim()))
      .slice(-8)
      .map((m) => ({
        role: m.role,
        content: m.content,
      }))

    // Auto-update session title if it's the first message
    const updatedTitle =
      activeSession.title === 'محادثة جديدة'
        ? trimmed.length > 26
          ? `${trimmed.slice(0, 26)}...`
          : trimmed
        : activeSession.title

    // Append user message immediately
    setSessions((prev) =>
      prev.map((s) =>
        s.id === activeSessionId
          ? {
              ...s,
              title: updatedTitle,
              messages: [...s.messages, newUserMessage],
            }
          : s
      )
    )

    setInput('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
    setIsLoading(true)

    try {
      const response = await sendChatMessage(trimmed, history, profileContext(studentProfile))
      const assistantMessageId = response.request_id || `asst-${Date.now()}`
      const newAssistantMessage: UIMessage = {
        id: assistantMessageId,
        role: 'assistant',
        content: response.answer,
        citations: response.citations,
        status: response.status,
        timestamp: new Date().toLocaleTimeString('ar-SA', {
          hour: '2-digit',
          minute: '2-digit',
        }),
      }

      setSessions((prev) =>
        prev.map((s) =>
          s.id === activeSessionId
            ? {
                ...s,
                messages: [...s.messages, newAssistantMessage],
              }
            : s
        )
      )
    } catch (error) {
      setInput(trimmed)
      const errorMessage: UIMessage = {
        id: `err-${Date.now()}`,
        role: 'assistant',
        content: error instanceof Error ? error.message : 'حدث خطأ أثناء معالجة استفسارك. يرجى المحاولة مرة أخرى.',
        isError: true,
        timestamp: new Date().toLocaleTimeString('ar-SA', {
          hour: '2-digit',
          minute: '2-digit',
        }),
      }

      setSessions((prev) =>
        prev.map((s) =>
          s.id === activeSessionId
            ? {
                ...s,
                messages: [...s.messages, errorMessage],
              }
            : s
        )
      )
    } finally {
      pendingSessionRef.current = null
      setIsLoading(false)
    }
  }

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    sendMessageWithQuery(input)
  }

  // Suggested questions chip items
  const suggestedChips = [
    'كيف أعرف المتطلب السابق؟',
    'ما هي شروط الانسحاب؟',
    'وماذا عن الحد الأدنى للعبء؟',
  ]

  const welcomeQuestions = [
    { label: 'اللوائح الأكاديمية', query: 'ما هي شروط الانسحاب؟' },
    { label: 'متطلبات المقررات', query: 'كيف أعرف المتطلب السابق؟' },
    { label: 'الخطة الدراسية', query: 'ما متطلبات تخصص هندسة الحاسوب؟' },
    { label: 'العبء الدراسي', query: 'ما الحد الأدنى للعبء الدراسي؟' },
  ]

  return (
    <div className="h-screen flex bg-gray-50 text-gray-800 antialiased overflow-hidden" dir="rtl">
      {/* 2. Collapsible Sidebar (Positioned on the Right in RTL) */}
      <Sidebar
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={(id) => setActiveSessionId(id)}
        onNewChat={handleNewChat}
        onDeleteSession={handleDeleteSession}
      />

      {/* Main Chat Interface */}
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden">
        {/* Sticky Header */}
        <header className="sticky top-0 z-30 bg-white/95 backdrop-blur-sm border-b border-gray-200 shadow-sm shrink-0">
          <div className="max-w-4xl mx-auto px-3 sm:px-4 py-3 flex items-center justify-between">
            <div className="flex items-center gap-2.5 sm:gap-3 min-w-0">
              {/* Sidebar Toggle Button */}
              <button
                type="button"
                onClick={() => setIsSidebarOpen(!isSidebarOpen)}
                className="p-2 rounded-xl text-gray-600 hover:text-blue-600 hover:bg-blue-50 border border-gray-200 transition active:scale-95"
                title="فتح / إغلاق سجل المحادثات"
              >
                <PanelRight className="w-5 h-5" />
              </button>

              <div className="w-10 h-10 rounded-xl bg-blue-50 border border-blue-200 flex items-center justify-center text-blue-600 shadow-inner shrink-0">
                <GraduationCap className="w-6 h-6" />
              </div>

              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h1 className="text-base sm:text-lg font-bold text-blue-600 tracking-tight truncate">
                    {activeSession.title && activeSession.title !== 'محادثة جديدة'
                      ? activeSession.title
                      : 'المرشد الأكاديمي الذكي'}
                  </h1>
                  <span className="hidden xs:inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-blue-100 text-blue-700 shrink-0">
                    <Sparkles className="w-3 h-3 ml-1 text-blue-600" />
                    جامعي
                  </span>
                </div>
                <p className="text-xs text-gray-500 hidden sm:block truncate">
                  مساعدك الذكي للإرشاد واللوائح والخطط الدراسية
                </p>
              </div>
            </div>

            <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
              {/* Student Profile Button (Feature 7 & 8) */}
              <button
                type="button"
                onClick={() => setIsProfileOpen(true)}
                title="الملف الأكاديمي وخطة الطالب"
                className="p-2 sm:px-3 sm:py-1.5 text-xs font-medium text-gray-700 hover:text-blue-600 hover:bg-blue-50 rounded-xl border border-gray-200 hover:border-blue-200 flex items-center gap-1.5 transition active:scale-95 group"
              >
                <User className="w-4 h-4 text-gray-500 group-hover:text-blue-600 transition-colors" />
                <span className="hidden sm:inline">
                  {studentProfile?.name ? studentProfile.name.split(' ')[0] : 'الملف الأكاديمي'}
                </span>
                {studentProfile?.planVersion && (
                  <span className="hidden md:inline-flex text-[10px] bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded font-mono font-semibold">
                    {studentProfile.planVersion}
                  </span>
                )}
              </button>

              {/* Clear Current Chat Button */}
              <button
                type="button"
                onClick={handleClearActiveSession}
                disabled={messages.length === 0 || pendingSessionRef.current === activeSessionId}
                title="مسح رسائل هذه المحادثة"
                className="p-2 sm:px-3 sm:py-1.5 text-xs font-medium text-gray-600 hover:text-red-600 hover:bg-red-50 rounded-xl border border-gray-200 hover:border-red-200 flex items-center gap-1.5 transition active:scale-95 disabled:opacity-30 disabled:pointer-events-none group"
              >
                <Trash2 className="w-4 h-4 text-gray-400 group-hover:text-red-500 transition-colors" />
                <span className="hidden sm:inline">مسح</span>
              </button>

              {/* Connection status badge */}
              <div role="status" className={`flex items-center gap-1.5 px-2.5 py-1 sm:px-3 border rounded-full text-xs shrink-0 ${connectionState.style}`}>
                <span className={`w-2 h-2 rounded-full ${connectionState.dot}`}></span>
                <span className="font-medium text-[11px] sm:text-xs">{connectionState.label}</span>
              </div>
            </div>
          </div>
        </header>

        {/* Scrollable Main Chat Area */}
        <main className="flex-1 overflow-y-auto px-3 py-4 sm:p-6 space-y-4">
          <div className="max-w-4xl mx-auto flex flex-col justify-between min-h-full">
            {/* Empty Welcome State */}
            {messages.length === 0 ? (
              <div className="my-auto py-6 sm:py-8 flex flex-col items-center justify-center text-center">
                <div className="bg-white rounded-2xl border border-gray-200 p-5 sm:p-8 shadow-sm max-w-xl w-full mx-auto">
                  <div className="w-14 h-14 mx-auto mb-4 rounded-2xl bg-blue-50 text-blue-600 flex items-center justify-center shadow-xs">
                    <BookOpen className="w-7 h-7" />
                  </div>
                  <h2 className="text-lg sm:text-xl font-bold text-gray-800 mb-2">
                    مرحباً بك في نظام الإرشاد الأكاديمي الذكي
                  </h2>
                  <p className="text-xs sm:text-sm text-gray-500 mb-6 leading-relaxed">
                    أنا هنا لمساعدتك في اللوائح الأكاديمية، متطلبات التخرج، وشروط الحذف والإضافة، مع متابعة سياق المحادثة الحالية.
                  </p>

                  <div className="text-right w-full">
                    <p className="text-xs font-semibold text-gray-600 mb-2.5 flex items-center gap-1">
                      <Sparkles className="w-3.5 h-3.5 text-blue-600" />
                      <span>أسئلة شائعة لبدء المحادثة:</span>
                    </p>
                    <div className="grid grid-cols-1 gap-2">
                      {welcomeQuestions.map((item, idx) => (
                        <button
                          key={idx}
                          type="button"
                          disabled={isLoading}
                          onClick={() => sendMessageWithQuery(item.query)}
                          className="w-full text-right p-3 rounded-xl bg-gray-50 hover:bg-blue-50 hover:border-blue-200 border border-gray-200 text-xs sm:text-sm text-gray-700 hover:text-blue-700 transition flex items-center justify-between group active:scale-[0.99]"
                        >
                          <div className="flex flex-col min-w-0 pr-1">
                            <span className="font-medium text-gray-800 group-hover:text-blue-800 truncate">
                              {item.query}
                            </span>
                            <span className="text-[11px] text-gray-400 group-hover:text-blue-500 mt-0.5">
                              {item.label}
                            </span>
                          </div>
                          <Send className="w-3.5 h-3.5 text-gray-400 group-hover:text-blue-600 transform -scale-x-100 transition shrink-0 mr-2" />
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              /* Message Bubbles Container */
              <div className="space-y-4 pb-2" role="log" aria-live="polite" aria-busy={isLoading && pendingSessionRef.current === activeSessionId}>
                {messages.map((message) => (
                  <MessageBubble key={message.id} message={message} />
                ))}

                {/* Loading Indicator */}
                {isLoading && pendingSessionRef.current === activeSessionId && (
                  <div className="flex flex-col items-end" role="status">
                    <div className="ml-auto bg-white border border-gray-200 px-4 py-3 rounded-2xl rounded-bl-none shadow-sm max-w-[85%] sm:max-w-[75%]">
                      <div className="flex items-center gap-2 text-xs font-semibold text-blue-600 mb-2 pb-1.5 border-b border-gray-100">
                        <GraduationCap className="w-4 h-4" />
                        <span>المرشد الأكاديمي</span>
                      </div>
                      <div className="flex items-center gap-3 text-xs sm:text-sm text-gray-500">
                        <span>جاري مراجعة اللائحة وإعداد الرد...</span>
                        <div className="flex items-center gap-1">
                          <span className="w-2 h-2 rounded-full bg-blue-600 animate-bounce [animation-delay:0ms]"></span>
                          <span className="w-2 h-2 rounded-full bg-blue-600 animate-bounce [animation-delay:150ms]"></span>
                          <span className="w-2 h-2 rounded-full bg-blue-600 animate-bounce [animation-delay:300ms]"></span>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* Auto-scroll anchor */}
                <div ref={messagesEndRef} />
              </div>
            )}
          </div>
        </main>

        {/* Sticky Bottom Area */}
        <footer className="sticky bottom-0 z-30 p-3 sm:p-4 bg-white border-t border-gray-200 shrink-0">
          <div className="max-w-4xl mx-auto">
            {/* Suggested Questions Row */}
            <div className="mb-2.5">
              <div className="flex items-center gap-2 overflow-x-auto pb-1 sm:pb-0 sm:flex-wrap no-scrollbar">
                <span className="text-[11px] font-semibold text-gray-400 shrink-0 hidden sm:inline-flex items-center gap-1">
                  <Sparkles className="w-3 h-3 text-blue-500" />
                  أسئلة مقترحة:
                </span>
                {suggestedChips.map((q, idx) => (
                  <button
                    key={idx}
                    type="button"
                    disabled={isLoading}
                    onClick={() => sendMessageWithQuery(q)}
                    className="shrink-0 text-xs px-3 py-1.5 rounded-full bg-blue-50/80 hover:bg-blue-100 text-blue-700 hover:text-blue-800 border border-blue-200/90 hover:border-blue-300 font-medium transition shadow-2xs active:scale-95 disabled:opacity-50 disabled:pointer-events-none flex items-center gap-1.5"
                    title={`إرسال: "${q}"`}
                  >
                    <span>{q}</span>
                    <Send className="w-3 h-3 text-blue-400 transform -scale-x-100" />
                  </button>
                ))}
              </div>
            </div>

            {/* Textarea Input Form */}
            <form
              onSubmit={handleSubmit}
              className="flex items-end gap-2 bg-gray-50 p-1.5 sm:p-2 rounded-2xl border border-gray-300 focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-100 transition"
            >
              <div className="flex-1 min-w-0">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={handleInputChange}
                  onKeyDown={handleKeyDown}
                  placeholder="اكتب استفسارك الأكاديمي هنا... (اضغط Enter للإرسال، وShift+Enter لسطر جديد)"
                  rows={1}
                  maxLength={2000}
                  aria-label="استفسارك الأكاديمي"
                  disabled={isLoading}
                  className="w-full px-3 py-2 bg-transparent text-sm sm:text-base text-gray-800 placeholder-gray-400 focus:outline-none resize-none max-h-36 leading-relaxed disabled:opacity-50"
                  dir="rtl"
                />
              </div>
              <button
                type="submit"
                disabled={!input.trim() || isLoading}
                className="p-2.5 sm:p-3 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-medium shadow-sm transition active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-blue-600 shrink-0 flex items-center justify-center"
                title="إرسال (Enter)"
              >
                <Send className="w-4 h-4 sm:w-5 sm:h-5 transform -scale-x-100" />
              </button>
            </form>

            {/* Bottom Hints */}
            <div className="flex flex-col sm:flex-row items-center justify-between text-[11px] text-gray-400 mt-2 px-1 gap-1">
              <span className="flex items-center gap-1 text-gray-500">
                <HardDrive className="w-3 h-3 text-blue-500" />
                <span>تحفظ المحادثات والذاكرة محلياً على جهازك</span>
              </span>
              <span className="hidden sm:inline">Enter للإرسال • Shift+Enter لسطر جديد</span>
            </div>
          </div>
        </footer>
      </div>

      {/* Feature 7 & 8: Student Profile & Study Plan Modal */}
      <ProfileModal
        isOpen={isProfileOpen}
        onClose={() => setIsProfileOpen(false)}
        onProfileSaved={(updated) => setStudentProfile(updated)}
      />
    </div>
  )
}
