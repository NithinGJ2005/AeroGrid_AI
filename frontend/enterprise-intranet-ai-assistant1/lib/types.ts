export type Scope = 'all' | 'docs' | 'sql'

export type Classification = 'Internal' | 'Confidential' | 'Restricted'

/** Contract: `filename`, `page`, `document_id`. Remaining fields are optional enrichments. */
export interface Citation {
  filename: string
  page: number
  document_id: string
  section?: string
  excerpt?: string
  classification?: Classification
  updated_at?: string
  knowledge_base?: string
}

export interface ChatRequest {
  message: string
}

export interface ChatResponse {
  response: string
  citations: Citation[]
}

/** Contract: `subject`, `permissions`. Remaining fields are optional enrichments. */
export interface Session {
  subject: string
  permissions: string[]
  display_name?: string
  role?: string
  department?: string
  claims?: Record<string, unknown>
}

export interface McpTool {
  name: string
  description?: string
  parameters?: Record<string, string>
}

export type ToolCallStatus = 'running' | 'complete' | 'error'

export interface ToolCall {
  tool: string
  args: Record<string, string | number>
  status: ToolCallStatus
  detail: string
  summary?: string
  durationMs?: number
}

export interface MessageError {
  status: number
  title: string
  message: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: number
  author?: string
  scope: Scope
  folders?: string[]
  citations?: Citation[]
  toolCalls?: ToolCall[]
  error?: MessageError
  latencyMs?: number
  cancelled?: boolean
}

export interface Conversation {
  id: string
  title: string
  updatedAt: number
  archived?: boolean
  messages: ChatMessage[]
}

export type AuditStatus = 'allowed' | 'denied' | 'throttled' | 'error' | 'cancelled'

export interface AuditEvent {
  id: string
  at: number
  event: 'session_verify' | 'assistant_chat' | 'mcp_tool_execute' | 'mcp_tools_list'
  status: AuditStatus
  latencyMs: number
  correlationId: string
  detail?: string
}

export type InflightPhase = 0 | 1 | 2
