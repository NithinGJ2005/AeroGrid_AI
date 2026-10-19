import type { ChatResponse, McpTool, Session } from './types'

export const DEMO_SESSION: Session = {
  subject: 'emp_48213',
  permissions: ['employee', 'documents:read', 'database:read'],
  display_name: 'Elena Marsh',
  role: 'analyst',
  department: 'Data Engineering',
  claims: {
    iss: 'https://sso.acme.internal',
    aud: 'intranet-assistant',
    sub: 'emp_48213',
    roles: ['employee', 'database:read'],
    dept: 'data-engineering',
    clearance: 'confidential',
    iat: 1792137600,
    exp: 1792166400,
  },
}

export const DEMO_TOOLS: McpTool[] = [
  {
    name: 'search_documents',
    description: 'Semantic + keyword retrieval over indexed internal policy documents.',
    parameters: { query: 'string', limit: 'integer', folder: 'string?' },
  },
  {
    name: 'query_database',
    description: 'Executes an approved, parameterized read-only query against the internal catalog DB.',
    parameters: { template: 'string', params: 'object' },
  },
]

const ANSWERS: { match: RegExp; response: ChatResponse }[] = [
  {
    match: /paternity|maternity|parental|leave/i,
    response: {
      response: `### Parental Leave Policy (FY2026)

Acme provides **paid parental leave** to all full-time employees after **90 days** of continuous service.

| Leave type | Paid duration | Eligibility |
| --- | --- | --- |
| Primary caregiver | 20 weeks at 100% base pay | Birth, adoption, or surrogacy |
| Secondary caregiver | 12 weeks at 100% base pay | Birth, adoption, or surrogacy |
| Phased return | 4 weeks at 80% schedule | Available after either leave |

**Key requirements**

- Notify your manager and HR Partner at least **30 days** before the expected start date where possible.
- Leave may be taken in up to **two blocks** within 12 months of the qualifying event.
- Benefits coverage (medical, dental, 401k match) continues unchanged during leave.

For the request form, file a ticket under **HR › Leave of Absence** in the internal service desk.`,
      citations: [
        {
          filename: 'hr_benefits_2026.pdf',
          page: 14,
          document_id: 'doc_hr_0142',
          section: '§4.2 Parental Leave',
          excerpt:
            'Full-time employees with at least ninety (90) days of continuous service are eligible for up to twenty (20) weeks of paid leave as a primary caregiver, or twelve (12) weeks as a secondary caregiver, paid at one hundred percent (100%) of base salary.',
          classification: 'Internal',
          updated_at: '2026-10-16T08:12:00Z',
          knowledge_base: 'HR & Employee Benefits',
        },
        {
          filename: 'hr_benefits_2026.pdf',
          page: 15,
          document_id: 'doc_hr_0142',
          section: '§4.3 Scheduling & Notice',
          excerpt:
            'Employees should provide notice to their manager and HR Business Partner no fewer than thirty (30) days prior to the anticipated start of leave. Leave may be taken in no more than two (2) separate blocks within twelve (12) months.',
          classification: 'Internal',
          updated_at: '2026-10-16T08:12:00Z',
          knowledge_base: 'HR & Employee Benefits',
        },
        {
          filename: 'benefits_continuation.md',
          page: 2,
          document_id: 'doc_hr_0157',
          section: 'Coverage During Leave',
          excerpt:
            'Medical, dental, vision, and retirement plan contributions (including employer match) continue without interruption during any approved paid leave.',
          classification: 'Internal',
          updated_at: '2026-09-02T14:40:00Z',
          knowledge_base: 'HR & Employee Benefits',
        },
      ],
    },
  },
  {
    match: /employee|staff|directory|data engineering|department/i,
    response: {
      response: `### Data Engineering — Active Staff (8)

Results returned from the approved \`staff_directory_by_department\` template. Compensation fields are excluded for your role.

| Employee | Title | Location | Manager |
| --- | --- | --- | --- |
| Elena Marsh | Senior Analyst | Austin | R. Okafor |
| Raymond Okafor | Director, Data Engineering | Austin | C. Lindqvist |
| Priya Raman | Staff Data Engineer | Toronto | R. Okafor |
| Tomás Ferreira | Data Engineer II | Lisbon | P. Raman |
| Hana Sato | Data Engineer II | Remote (JP) | P. Raman |
| Marcus Webb | Analytics Engineer | Austin | R. Okafor |
| Ines Duarte | Data Platform SRE | Lisbon | R. Okafor |
| Jonah Kline | Data Engineer I | Toronto | P. Raman |

- **Headcount:** 8 active, 1 open requisition (\`REQ-2291\`)
- **Last directory sync:** today, 06:00 UTC`,
      citations: [
        {
          filename: 'catalog.db › staff_directory',
          page: 1,
          document_id: 'sql_tpl_staff_dept',
          section: 'Template: staff_directory_by_department',
          excerpt:
            "SELECT full_name, title, location, manager_name FROM staff_directory WHERE department = :department AND status = 'active' ORDER BY title_rank DESC; -- params: { department: 'Data Engineering' }",
          classification: 'Confidential',
          updated_at: '2026-10-16T06:00:00Z',
          knowledge_base: 'Staff & Directory Query',
        },
      ],
    },
  },
  {
    match: /ssh|api key|rotat|credential|secret/i,
    response: {
      response: `### Credential Rotation Requirements

Per **IT Security & Compliance Guidelines v4.2**, all production credentials must be rotated on a fixed cadence and immediately upon suspected exposure.

| Credential | Max lifetime | Owner |
| --- | --- | --- |
| SSH keys (production bastion) | 90 days | Individual engineer |
| Production API keys | 30 days | Service owner |
| Service account tokens | 7 days (automated) | Platform team |

**Rules**

1. Keys must be generated on a **managed workstation** using \`ed25519\` (SSH) or the internal vault CLI (API keys).
2. Never paste keys into chat, tickets, or source control — use \`vault://\` references.
3. On suspected exposure, revoke within **1 hour** and file a \`SEC-INCIDENT\` ticket.
4. Rotation is audited monthly; overdue keys are **auto-disabled** after a 72-hour grace period.`,
      citations: [
        {
          filename: 'it_security_sop.md',
          page: 3,
          document_id: 'doc_sec_0042',
          section: 'Section 3 — Credential Lifecycle',
          excerpt:
            'Production SSH keys SHALL NOT exceed a lifetime of ninety (90) days. Production API keys SHALL be rotated at intervals not exceeding thirty (30) days. Credentials suspected of exposure MUST be revoked within one (1) hour of detection.',
          classification: 'Restricted',
          updated_at: '2026-08-21T10:00:00Z',
          knowledge_base: 'IT Security & Compliance Guidelines',
        },
        {
          filename: 'it_security_sop.md',
          page: 4,
          document_id: 'doc_sec_0042',
          section: 'Section 3.4 — Enforcement',
          excerpt:
            'Credentials exceeding their maximum lifetime will be automatically disabled following a seventy-two (72) hour grace period. Rotation compliance is reviewed monthly by the Security Operations team.',
          classification: 'Restricted',
          updated_at: '2026-08-21T10:00:00Z',
          knowledge_base: 'IT Security & Compliance Guidelines',
        },
      ],
    },
  },
  {
    match: /travel|expense|reimburse/i,
    response: {
      response: `### Travel Expense Reimbursement — Approval Flow

1. **Submit** the claim in the Finance portal within **30 days** of trip completion, with itemized receipts for anything over **$25**.
2. **Manager review** — your direct manager approves or returns the claim within 5 business days.
3. **Finance audit** — claims over **$2,500** or containing exceptions (upgrades, alcohol, personal days) are routed to Finance Operations.
4. **VP sign-off** — required only for international travel over **$10,000** total.
5. **Payout** — approved claims are reimbursed in the next payroll cycle.

| Category | Daily cap |
| --- | --- |
| Lodging (Tier 1 cities) | $325 |
| Lodging (other) | $210 |
| Meals & incidentals | $85 |

> Claims submitted after 60 days require Director-level exception approval.`,
      citations: [
        {
          filename: 'finance_travel_policy.pdf',
          page: 6,
          document_id: 'doc_fin_0019',
          section: '§2 Approval Workflow',
          excerpt:
            'All expense claims must be submitted within thirty (30) days. Claims exceeding $2,500 USD, or containing exception categories, are subject to secondary review by Finance Operations prior to reimbursement.',
          classification: 'Internal',
          updated_at: '2026-07-01T09:00:00Z',
          knowledge_base: 'Finance Policy',
        },
        {
          filename: 'finance_travel_policy.pdf',
          page: 9,
          document_id: 'doc_fin_0019',
          section: 'Appendix A — Per Diem Caps',
          excerpt:
            'Lodging: Tier 1 metropolitan areas $325/night; all other locations $210/night. Meals and incidental expenses: $85/day.',
          classification: 'Internal',
          updated_at: '2026-07-01T09:00:00Z',
          knowledge_base: 'Finance Policy',
        },
      ],
    },
  },
  {
    match: /budget/i,
    response: {
      response: `### Department Budget — Data Engineering (FY2026)

| Line item | Allocated | Spent YTD | Remaining |
| --- | --- | --- | --- |
| Personnel | $1,840,000 | $1,412,300 | $427,700 |
| Infrastructure | $410,000 | $338,900 | $71,100 |
| Training & Travel | $48,000 | $21,450 | $26,550 |

- **Utilization:** 78.6% of total allocation through Q3.
- Infrastructure is tracking **6% above** linear burn — review planned for the Q4 checkpoint.`,
      citations: [
        {
          filename: 'catalog.db › dept_budgets',
          page: 1,
          document_id: 'sql_tpl_budget_dept',
          section: 'Template: department_budget_lookup',
          excerpt:
            'SELECT line_item, allocated, spent_ytd, allocated - spent_ytd AS remaining FROM dept_budgets WHERE department = :department AND fiscal_year = :fy; -- params: { department: "Data Engineering", fy: 2026 }',
          classification: 'Confidential',
          updated_at: '2026-10-15T23:00:00Z',
          knowledge_base: 'Department Budget Lookup',
        },
      ],
    },
  },
]

export function resolveDemoAnswer(message: string): ChatResponse {
  const hit = ANSWERS.find((a) => a.match.test(message))
  if (hit) return hit.response
  return {
    response: `I searched the indexed intranet knowledge bases but couldn't find a verified source that directly answers:

> ${message.slice(0, 240)}

**Suggestions**

- Narrow the scope to a specific knowledge base using the folder filter.
- Rephrase using policy terminology (e.g. *"leave of absence"* instead of *"time off"*).
- For data questions, use one of the **Approved Database Queries** in the sidebar.

I will not answer from general model knowledge when no verified intranet source is available.`,
    citations: [],
  }
}
