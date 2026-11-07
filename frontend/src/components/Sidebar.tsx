import React from 'react'
import {
  Plus,
  MessageSquare,
  Trash2,
  X,
  Sparkles,
  Clock,
  ChevronLeft,
} from 'lucide-react'
import type { ChatSession } from '../types/chat'

interface SidebarProps {
  isOpen: boolean
  onClose: () => void
  sessions: ChatSession[]
  activeSessionId: string
  onSelectSession: (sessionId: string) => void
  onNewChat: () => void
  onDeleteSession: (sessionId: string) => void
}

export const Sidebar: React.FC<SidebarProps> = ({
  isOpen,
  onClose,
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
}) => {
  return (
    <>
      {/* Mobile Backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40 backdrop-blur-xs lg:hidden transition-opacity"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      {/* Sidebar Panel (Positioned on the Right for RTL) */}
      <aside
        className={`fixed lg:static top-0 right-0 z-40 h-full w-72 sm:w-80 bg-white border-l border-gray-200 flex flex-col transition-transform duration-300 ease-in-out shrink-0 select-none shadow-xl lg:shadow-none ${
          isOpen ? 'translate-x-0' : 'translate-x-full lg:translate-x-0 lg:w-72'
        }`}
        dir="rtl"
      >
        {/* Sidebar Header */}
        <div className="p-4 border-b border-gray-100 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center border border-blue-100">
              <MessageSquare className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-gray-800">سجل المحادثات</h2>
              <p className="text-[11px] text-gray-400">الجلسات الأكاديمية المحفوظة</p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 lg:hidden transition"
            title="إغلاق القائمة"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* New Chat Button */}
        <div className="p-3 border-b border-gray-100 shrink-0">
          <button
            type="button"
            onClick={() => {
              onNewChat()
              if (window.innerWidth < 1024) onClose()
            }}
            className="w-full py-2.5 px-3.5 rounded-xl bg-blue-600 hover:bg-blue-700 active:scale-[0.98] text-white text-xs sm:text-sm font-semibold flex items-center justify-center gap-2 shadow-sm transition group"
          >
            <Plus className="w-4 h-4 transition-transform group-hover:rotate-90 duration-200" />
            <span>محادثة جديدة</span>
          </button>
        </div>

        {/* Sessions List */}
        <div className="flex-1 overflow-y-auto p-2.5 space-y-1.5">
          <div className="text-[11px] font-semibold text-gray-400 px-2 py-1 flex items-center justify-between">
            <span>المحادثات السابقة ({sessions.length})</span>
            <Clock className="w-3 h-3" />
          </div>

          {sessions.length === 0 ? (
            <div className="text-center py-8 px-4 text-xs text-gray-400">
              لا توجد محادثات سابقة حتى الآن.
            </div>
          ) : (
            sessions.map((session) => {
              const isActive = session.id === activeSessionId
              const messageCount = session.messages.length

              return (
                <div
                  key={session.id}
                  onClick={() => {
                    onSelectSession(session.id)
                    if (window.innerWidth < 1024) onClose()
                  }}
                  className={`group relative flex items-center justify-between p-2.5 rounded-xl border text-xs sm:text-sm transition-all cursor-pointer ${
                    isActive
                      ? 'bg-blue-50/90 border-blue-200 text-blue-900 shadow-xs font-semibold'
                      : 'bg-white hover:bg-gray-50/90 border-transparent hover:border-gray-200 text-gray-700'
                  }`}
                >
                  <div className="flex items-center gap-2.5 min-w-0 pr-1 flex-1">
                    <MessageSquare
                      className={`w-4 h-4 shrink-0 transition-colors ${
                        isActive ? 'text-blue-600' : 'text-gray-400 group-hover:text-blue-500'
                      }`}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs sm:text-sm font-medium leading-snug">
                        {session.title || 'محادثة جديدة'}
                      </p>
                      <div className="flex items-center gap-1.5 text-[10px] text-gray-400 mt-0.5">
                        <span>
                          {new Date(session.createdAt).toLocaleDateString('ar-SA', {
                            month: 'short',
                            day: 'numeric',
                          })}
                        </span>
                        <span>•</span>
                        <span>{messageCount} رسائل</span>
                        {session.summary && (
                          <span
                            title={session.summary}
                            className="inline-flex items-center text-blue-600 font-normal mr-1"
                          >
                            <Sparkles className="w-2.5 h-2.5 ml-0.5" />
                            ملخّص
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Actions / Delete Session */}
                  <div className="flex items-center gap-1 shrink-0 mr-1">
                    {sessions.length > 1 && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          onDeleteSession(session.id)
                        }}
                        className="opacity-0 group-hover:opacity-100 p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition"
                        title="حذف هذه المحادثة"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                    {isActive && (
                      <ChevronLeft className="w-4 h-4 text-blue-500 shrink-0" />
                    )}
                  </div>
                </div>
              )
            })
          )}
        </div>

        {/* Sidebar Footer Hint */}
        <div className="p-3 border-t border-gray-100 bg-gray-50/70 text-[11px] text-gray-400 text-center shrink-0">
          <span>يتم حفظ الجلسات والذاكرة محلياً</span>
        </div>
      </aside>
    </>
  )
}
