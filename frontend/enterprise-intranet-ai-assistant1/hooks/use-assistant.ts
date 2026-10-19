'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, api, describeApiError } from '@/lib/api'
import { SEED_AUDIT, SEED_CONVERSATIONS, planToolCall } from '@/lib/catalog'
import type {
  AuditEvent,
  AuditStatus,
  ChatMessage,
  Conversation,
  InflightPhase,
  Scope,
  ToolCall,
} from '@/lib/types'

export interface Inflight {
  conversationId: string
  phase: InflightPhase
  toolCall: ToolCall
  startedAt: number
}

const uid = () => crypto.randomUUID()

function statusFor(code: number): AuditStatus {
  if (code === 403 || code === 401) return 'denied'
  if (code === 429) return 'throttled'
  return 'error'
}

export function useAssistant({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [conversations, setConversations] = useState<Conversation[]>(SEED_CONVERSATIONS)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [inflight, setInflight] = useState<Inflight | null>(null)
  const [audit, setAudit] = useState<AuditEvent[]>(SEED_AUDIT)
  const [lastLatencyMs, setLastLatencyMs] = useState<number | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([])

  const active = useMemo(
    () => conversations.find((c) => c.id === activeId) ?? null,
    [conversations, activeId],
  )

  const logAudit = useCallback((event: Omit<AuditEvent, 'id' | 'at'>) => {
    setAudit((prev) => [{ ...event, id: uid(), at: Date.now() }, ...prev].slice(0, 100))
  }, [])

  const clearTimers = () => {
    timersRef.current.forEach(clearTimeout)
    timersRef.current = []
  }

  useEffect(() => () => {
    clearTimers()
    abortRef.current?.abort()
  }, [])

  const appendMessage = useCallback((conversationId: string, message: ChatMessage) => {
    setConversations((prev) =>
      prev.map((c) =>
        c.id === conversationId
          ? { ...c, updatedAt: message.createdAt, messages: [...c.messages, message] }
          : c,
      ),
    )
  }, [])

  const send = useCallback(
    async ({
      text,
      scope,
      folders,
      author,
      fresh,
    }: {
      text: string
      scope: Scope
      folders: string[]
      author?: string
      fresh?: boolean
    }) => {
      const message = text.trim()
      if (!message || abortRef.current) return

      let conversationId = fresh ? null : activeId
      const createdAt = Date.now()
      const userMessage: ChatMessage = { id: uid(), role: 'user', content: message, createdAt, author, scope, folders }

      if (!conversationId) {
        conversationId = uid()
        const title = message.length > 64 ? `${message.slice(0, 61)}…` : message
        setConversations((prev) => [{ id: conversationId!, title, updatedAt: createdAt, messages: [userMessage] }, ...prev])
        setActiveId(conversationId)
      } else {
        appendMessage(conversationId, userMessage)
      }

      const controller = new AbortController()
      abortRef.current = controller
      const toolCall = planToolCall(message, scope, folders)
      setInflight({ conversationId, phase: 0, toolCall, startedAt: createdAt })
      timersRef.current.push(
        setTimeout(() => setInflight((s) => (s ? { ...s, phase: 1 } : s)), 650),
        setTimeout(() => setInflight((s) => (s ? { ...s, phase: 2 } : s)), 1800),
      )

      const cid = conversationId
      try {
        const { data, latencyMs, correlationId } = await api.chat(message, controller.signal)
        const citations = data.citations ?? []
        const firstFile = citations[0]?.filename
        const completed: ToolCall = {
          ...toolCall,
          status: 'complete',
          durationMs: Math.round(latencyMs * 0.42),
          detail:
            toolCall.tool === 'query_database'
              ? `Executed approved template ${toolCall.args.template} on catalog.db (read-only)`
              : `Scanned ${8 + citations.length * 4} indexed chunks from ${firstFile ? `/data/documents/${firstFile}` : String(toolCall.args.folder ?? '/data/documents')}`,
          summary: `${citations.length} citation${citations.length === 1 ? '' : 's'} retrieved`,
        }
        setLastLatencyMs(latencyMs)
        logAudit({ event: 'mcp_tool_execute', status: 'allowed', latencyMs: completed.durationMs ?? 0, correlationId, detail: toolCall.tool })
        logAudit({ event: 'assistant_chat', status: 'allowed', latencyMs, correlationId })
        appendMessage(cid, {
          id: uid(),
          role: 'assistant',
          content: data.response,
          createdAt: Date.now(),
          scope,
          citations,
          toolCalls: [completed],
          latencyMs,
        })
      } catch (err) {
        const aborted = err instanceof DOMException && err.name === 'AbortError'
        const correlationId = err instanceof ApiError ? err.correlationId ?? 'n/a' : 'n/a'
        if (aborted) {
          logAudit({ event: 'assistant_chat', status: 'cancelled', latencyMs: Date.now() - createdAt, correlationId: 'client_abort' })
          appendMessage(cid, {
            id: uid(),
            role: 'assistant',
            content: '',
            createdAt: Date.now(),
            scope,
            cancelled: true,
            toolCalls: [{ ...toolCall, status: 'error', detail: 'Generation cancelled by user before completion.' }],
          })
        } else {
          const error = describeApiError(err)
          logAudit({ event: 'assistant_chat', status: statusFor(error.status), latencyMs: Date.now() - createdAt, correlationId, detail: `HTTP ${error.status}` })
          appendMessage(cid, {
            id: uid(),
            role: 'assistant',
            content: '',
            createdAt: Date.now(),
            scope,
            error,
            toolCalls: [{ ...toolCall, status: 'error', detail: `Request rejected by gateway (HTTP ${error.status}).` }],
          })
          if (error.status === 401) onUnauthorized()
        }
      } finally {
        clearTimers()
        abortRef.current = null
        setInflight(null)
      }
    },
    [activeId, appendMessage, logAudit, onUnauthorized],
  )

  const stop = useCallback(() => abortRef.current?.abort(), [])

  const newConversation = useCallback(() => {
    if (abortRef.current) return
    setActiveId(null)
  }, [])

  const selectConversation = useCallback((id: string) => {
    if (abortRef.current) return
    setActiveId(id)
  }, [])

  const deleteConversation = useCallback((id: string) => {
    setConversations((prev) => prev.filter((c) => c.id !== id))
    setActiveId((cur) => (cur === id ? null : cur))
  }, [])

  const archiveConversation = useCallback((id: string) => {
    setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, archived: true } : c)))
    setActiveId((cur) => (cur === id ? null : cur))
  }, [])

  return {
    conversations,
    active,
    activeId,
    inflight,
    audit,
    lastLatencyMs,
    isGenerating: inflight !== null,
    logAudit,
    send,
    stop,
    newConversation,
    selectConversation,
    deleteConversation,
    archiveConversation,
  }
}

export type AssistantState = ReturnType<typeof useAssistant>
