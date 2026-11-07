import React from 'react'
import {
  GraduationCap,
  AlertTriangle,
  HelpCircle,
  Info,
  AlertCircle,
  BookOpen,
} from 'lucide-react'
import type { UIMessage } from '../types/chat'
import { CitationCard } from './CitationCard'

export type { UIMessage }

interface MessageBubbleProps {
  message: UIMessage
}

export const MessageBubble: React.FC<MessageBubbleProps> = ({ message }) => {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div className="flex flex-col items-start">
        <div className="mr-auto bg-blue-600 text-white rounded-2xl rounded-br-none px-4 py-3 shadow-sm max-w-[85%] md:max-w-[75%] text-sm md:text-base leading-relaxed">
          <p className="whitespace-pre-wrap">{message.content}</p>
          <div className="text-[10px] mt-1.5 text-blue-100 text-left font-sans">
            {message.timestamp}
          </div>
        </div>
      </div>
    )
  }

  // Assistant Bubble rendering with the 4 API states
  const status = message.status || 'answered'

  // Determine state-specific styling & icon
  const getStateConfig = () => {
    if (message.isError) {
      return {
        badgeBg: 'bg-red-50 text-red-700 border-red-200',
        icon: <AlertCircle className="w-4 h-4 text-red-500 shrink-0" />,
        label: 'خطأ في معالجة الطلب',
        bubbleBorder: 'border-red-200 bg-red-50/20',
      }
    }

    switch (status) {
      case 'out_of_scope':
        return {
          badgeBg: 'bg-amber-50 text-amber-800 border-amber-200',
          icon: <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0" />,
          label: 'خارج نطاق الاختصاص',
          bubbleBorder: 'border-amber-200/80 bg-amber-50/10',
        }
      case 'needs_clarification':
        return {
          badgeBg: 'bg-blue-50 text-blue-800 border-blue-200',
          icon: <HelpCircle className="w-4 h-4 text-blue-500 shrink-0" />,
          label: 'يتطلب توضيحاً إضافياً',
          bubbleBorder: 'border-blue-200/80 bg-blue-50/10',
        }
      case 'insufficient_evidence':
        return {
          badgeBg: 'bg-rose-50 text-rose-800 border-rose-200',
          icon: <Info className="w-4 h-4 text-rose-500 shrink-0" />,
          label: 'شواهد غير كافية في اللائحة',
          bubbleBorder: 'border-rose-200/80 bg-rose-50/10',
        }
      case 'answered':
      default:
        return {
          badgeBg: 'bg-blue-50 text-blue-700 border-blue-100',
          icon: <GraduationCap className="w-4 h-4 text-blue-600 shrink-0" />,
          label: 'المرشد الأكاديمي',
          bubbleBorder: 'border-gray-200 bg-white',
        }
    }
  }

  const config = getStateConfig()
  const hasCitations =
    status === 'answered' && message.citations && message.citations.length > 0

  return (
    <div className="flex flex-col items-end">
      <div
        className={`ml-auto ${config.bubbleBorder} text-gray-800 border rounded-2xl rounded-bl-none p-4 md:p-5 shadow-sm max-w-[90%] md:max-w-[80%] text-sm md:text-base leading-relaxed transition-all`}
      >
        {/* State / Role Header Badge */}
        <div className="flex items-center justify-between gap-2 mb-2.5 pb-2 border-b border-gray-100">
          <div
            className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold border ${config.badgeBg}`}
          >
            {config.icon}
            <span>{config.label}</span>
          </div>

          <span className="text-[10px] text-gray-400 font-sans">
            {message.timestamp}
          </span>
        </div>

        {/* Message Content */}
        <p className="whitespace-pre-wrap text-gray-800 leading-relaxed break-words" role={message.isError ? 'alert' : undefined}>
          {message.content}
        </p>

        {/* Citations Section (When status === 'answered' and citations exist) */}
        {hasCitations && (
          <div className="mt-4 pt-3 border-t border-gray-100 space-y-2.5">
            <div className="flex items-center gap-1.5 text-xs font-bold text-gray-700">
              <BookOpen className="w-4 h-4 text-blue-600" />
              <span>المصادر والشواهد المعتمدة ({message.citations!.length}):</span>
            </div>
            <div className="space-y-2.5">
              {message.citations!.map((c, idx) => (
                <CitationCard key={c.source_id || idx} citation={c} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
