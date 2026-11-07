import type { Citation, ResponseStatus } from './api'

export interface UIMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  isError?: boolean
  status?: ResponseStatus
  timestamp: string
}

export interface ChatSession {
  id: string
  title: string
  summary: string
  messages: UIMessage[]
  createdAt: number
}
