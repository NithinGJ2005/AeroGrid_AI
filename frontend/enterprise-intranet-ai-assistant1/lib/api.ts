import type { ChatResponse, McpTool, MessageError, Session } from './types'

/**
 * Point this at the intranet gateway (e.g. `http://10.0.4.12:8000`).
 * When unset, requests go to the bundled same-origin demo handlers under `/api/v1`.
 */
const API_BASE = (process.env.NEXT_PUBLIC_INTRANET_API_BASE ?? '').replace(/\/$/, '')
const TOKEN_STORAGE_KEY = 'acme-intranet-bearer'

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public correlationId?: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export function getAuthToken(): string | null {
  if (typeof window === 'undefined') return null
  return window.sessionStorage.getItem(TOKEN_STORAGE_KEY)
}

export function setAuthToken(token: string | null) {
  if (typeof window === 'undefined') return
  if (token) window.sessionStorage.setItem(TOKEN_STORAGE_KEY, token)
  else window.sessionStorage.removeItem(TOKEN_STORAGE_KEY)
}

export interface Timed<T> {
  data: T
  latencyMs: number
  correlationId: string
}

function newCorrelationId() {
  return `cor_${crypto.randomUUID().replace(/-/g, '').slice(0, 12)}`
}

async function request<T>(path: string, init: RequestInit = {}): Promise<Timed<T>> {
  const correlationId = newCorrelationId()
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  headers.set('X-Correlation-ID', correlationId)
  if (init.body) headers.set('Content-Type', 'application/json')
  const token = getAuthToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const started = performance.now()
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers, cache: 'no-store' })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(503, 'Unable to reach the local inference gateway.', correlationId)
  }
  const latencyMs = Math.round(performance.now() - started)
  const serverCorrelation = res.headers.get('x-correlation-id') ?? correlationId

  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body?.detail ?? body?.message ?? detail
    } catch {}
    throw new ApiError(res.status, String(detail), serverCorrelation)
  }

  return { data: (await res.json()) as T, latencyMs, correlationId: serverCorrelation }
}

export const api = {
  chat: (message: string, signal?: AbortSignal) =>
    request<ChatResponse>('/api/v1/chat', {
      method: 'POST',
      body: JSON.stringify({ message }),
      signal,
    }),
  session: () => request<Session>('/api/v1/session'),
  tools: () => request<McpTool[] | { tools: McpTool[] }>('/api/v1/mcp/tools'),
}

export function describeApiError(err: unknown): MessageError {
  const status = err instanceof ApiError ? err.status : 500
  switch (status) {
    case 401:
      return {
        status,
        title: 'Authentication required',
        message: 'Your intranet session token is missing or expired. Configure a valid bearer token to continue.',
      }
    case 403:
      return {
        status,
        title: 'Permission Denied',
        message: 'Missing role for this document/database.',
      }
    case 429:
      return {
        status,
        title: 'Internal queue busy',
        message: 'Local GPU at capacity, retry in 5s.',
      }
    case 503:
      return {
        status,
        title: 'Service unavailable',
        message: 'Local inference service offline.',
      }
    default:
      return {
        status,
        title: 'Unexpected error',
        message: err instanceof Error ? err.message : 'The request could not be completed.',
      }
  }
}
