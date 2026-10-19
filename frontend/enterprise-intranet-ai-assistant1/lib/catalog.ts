import { resolveDemoAnswer } from './demo-backend'
import type { AuditEvent, Conversation, Scope, ToolCall } from './types'

export const SCOPES: { id: Scope; label: string; short: string }[] = [
  { id: 'all', label: 'All Intranet', short: 'All' },
  { id: 'docs', label: 'Policies & Docs', short: 'Docs' },
  { id: 'sql', label: 'Internal SQL DB', short: 'SQL' },
]

export interface KnowledgeBase {
  id: string
  name: string
  folder: string
  meta: string
  documents: number
}

export const KNOWLEDGE_BASES: KnowledgeBase[] = [
  { id: 'hr', name: 'HR & Employee Benefits', folder: '/data/documents/hr', meta: '12 docs · updated 2h ago', documents: 12 },
  { id: 'sec', name: 'IT Security & Compliance', folder: '/data/documents/security', meta: 'v4.2 · 31 docs', documents: 31 },
  { id: 'eng', name: 'Engineering Runbooks', folder: '/data/documents/engineering', meta: 'Architecture · 58 docs', documents: 58 },
  { id: 'fin', name: 'Finance Policy', folder: '/data/documents/finance', meta: '9 docs · updated 3d ago', documents: 9 },
]

export interface ApprovedQuery {
  id: string
  name: string
  template: string
  prompt: string
}

export const APPROVED_QUERIES: ApprovedQuery[] = [
  {
    id: 'staff',
    name: 'Staff & Directory Query',
    template: 'staff_directory_by_department',
    prompt: 'List all employees in the Data Engineering department',
  },
  {
    id: 'budget',
    name: 'Department Budget Lookup',
    template: 'department_budget_lookup',
    prompt: 'Show the FY2026 department budget for Data Engineering',
  },
  {
    id: 'assets',
    name: 'Asset & Hardware Registry',
    template: 'asset_registry_by_owner',
    prompt: 'Which hardware assets are currently assigned to me?',
  },
]

export const QUICK_PROMPTS: { title: string; prompt: string; tags: string[]; scope: Scope }[] = [
  { title: 'Find an internal policy', prompt: 'What is our annual paternity & maternity leave policy?', tags: ['HR Policy', 'PDF'], scope: 'docs' },
  { title: 'Look up a procedure', prompt: 'What are the rules for rotating SSH and production API keys?', tags: ['Security Guide'], scope: 'docs' },
  { title: 'Locate a resource', prompt: 'List all employees in the Data Engineering department', tags: ['SQL Catalog'], scope: 'sql' },
  { title: 'Explain a company process', prompt: 'Explain the travel expense reimbursement approval flow', tags: ['Finance Policy'], scope: 'docs' },
]

const DB_PATTERN = /employee|staff|directory|budget|asset|hardware|headcount|list all|assigned to me/i

export function planToolCall(message: string, scope: Scope, folders: string[]): ToolCall {
  const useDb = scope === 'sql' || (scope === 'all' && DB_PATTERN.test(message))
  if (useDb) {
    const template = /budget/i.test(message)
      ? 'department_budget_lookup'
      : /asset|hardware/i.test(message)
        ? 'asset_registry_by_owner'
        : 'staff_directory_by_department'
    return {
      tool: 'query_database',
      args: { template, department: 'Data Engineering' },
      status: 'running',
      detail: `Binding parameters for approved template ${template} on catalog.db (read-only)...`,
    }
  }
  const query = message
    .replace(/[^\w\s&-]/g, '')
    .split(/\s+/)
    .filter((w) => w.length > 3 && !/^(what|which|explain|about|does|have|with|that|this|from|there|their|rules)$/i.test(w))
    .slice(0, 4)
    .join(' ')
    .toLowerCase()
  const folder = folders[0] ?? '/data/documents'
  return {
    tool: 'search_documents',
    args: { query: query || message.slice(0, 40), limit: 3, ...(folders.length ? { folder } : {}) },
    status: 'running',
    detail: `Scanning indexed chunks under ${folder}...`,
  }
}

const now = Date.now()
const HOUR = 3_600_000
const DAY = 24 * HOUR

function seed(id: string, title: string, ageMs: number, scope: Scope, toolCall: ToolCall): Conversation {
  const at = now - ageMs
  const answer = resolveDemoAnswer(title)
  return {
    id,
    title,
    updatedAt: at,
    messages: [
      { id: `${id}-u`, role: 'user', content: title, createdAt: at - 4000, author: 'Elena Marsh', scope },
      {
        id: `${id}-a`,
        role: 'assistant',
        content: answer.response,
        createdAt: at,
        scope,
        citations: answer.citations,
        latencyMs: 2810,
        toolCalls: [
          {
            ...toolCall,
            status: 'complete',
            durationMs: 1240,
            summary: `${answer.citations.length} citation${answer.citations.length === 1 ? '' : 's'} retrieved`,
          },
        ],
      },
    ],
  }
}

export const SEED_CONVERSATIONS: Conversation[] = [
  seed('c1', 'Credential rotation rules for production API keys', 2 * HOUR, 'docs', {
    tool: 'search_documents',
    args: { query: 'rotation production api keys', limit: 3 },
    status: 'complete',
    detail: 'Scanned 22 indexed chunks from /data/documents/security/it_security_sop.md',
  }),
  seed('c2', 'Data Engineering budget remaining FY2026', 5 * HOUR, 'sql', {
    tool: 'query_database',
    args: { template: 'department_budget_lookup', department: 'Data Engineering', fy: 2026 },
    status: 'complete',
    detail: 'Executed approved template department_budget_lookup on catalog.db (read-only)',
  }),
  seed('c3', 'Parental leave eligibility after 90 days', DAY + 3 * HOUR, 'docs', {
    tool: 'search_documents',
    args: { query: 'parental leave eligibility', limit: 3 },
    status: 'complete',
    detail: 'Scanned 14 indexed chunks from /data/documents/hr/hr_benefits_2026.pdf',
  }),
  seed('c4', 'Travel reimbursement over $2,500', 3 * DAY, 'docs', {
    tool: 'search_documents',
    args: { query: 'travel reimbursement threshold', limit: 3 },
    status: 'complete',
    detail: 'Scanned 9 indexed chunks from /data/documents/finance/finance_travel_policy.pdf',
  }),
  seed('c5', 'Staff directory — Data Engineering', 5 * DAY, 'sql', {
    tool: 'query_database',
    args: { template: 'staff_directory_by_department', department: 'Data Engineering' },
    status: 'complete',
    detail: 'Executed approved template staff_directory_by_department on catalog.db (read-only)',
  }),
]

export const SEED_AUDIT: AuditEvent[] = [
  { id: 'a3', at: now - 2 * HOUR, event: 'mcp_tool_execute', status: 'allowed', latencyMs: 184, correlationId: 'cor_7f3a91c0d2e4', detail: 'search_documents' },
  { id: 'a2', at: now - 2 * HOUR - 2000, event: 'assistant_chat', status: 'allowed', latencyMs: 2810, correlationId: 'cor_7f3a91c0d2e4' },
  { id: 'a1', at: now - 5 * HOUR, event: 'mcp_tool_execute', status: 'denied', latencyMs: 12, correlationId: 'cor_1b88e04fa6c3', detail: 'query_database: payroll_by_employee' },
]

export const MODEL_INFO = {
  host: 'http://127.0.0.1:11434',
  model: 'qwen2.5:14b-instruct-q5_K_M',
  revision: 'sha256:9f2c…a41e',
  contextWindow: 4096,
}

export function estimateTokens(text: string) {
  return text.trim() ? Math.ceil(text.trim().length / 4) : 0
}
