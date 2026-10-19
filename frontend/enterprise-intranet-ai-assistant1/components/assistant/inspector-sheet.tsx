'use client'

import useSWR from 'swr'
import { KeyRound, Loader2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { api } from '@/lib/api'
import { MODEL_INFO } from '@/lib/catalog'
import type { AuditEvent, AuditStatus, McpTool, Session } from '@/lib/types'
import { cn } from '@/lib/utils'

interface InspectorSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  session?: Session
  sessionError?: unknown
  audit: AuditEvent[]
  onConfigureToken: () => void
}

export function InspectorSheet({ open, onOpenChange, session, sessionError, audit, onConfigureToken }: InspectorSheetProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full gap-0 sm:max-w-lg">
        <SheetHeader className="border-b">
          <SheetTitle>Security Inspector</SheetTitle>
          <SheetDescription>Session claims, MCP tool registry, and gateway audit trail.</SheetDescription>
        </SheetHeader>
        <Tabs defaultValue="session" className="flex min-h-0 flex-1 flex-col gap-0">
          <div className="border-b px-4 py-2">
            <TabsList>
              <TabsTrigger value="session">Session</TabsTrigger>
              <TabsTrigger value="tools">MCP Tools</TabsTrigger>
              <TabsTrigger value="audit">Audit Log</TabsTrigger>
              <TabsTrigger value="model">Model</TabsTrigger>
            </TabsList>
          </div>
          <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-4">
            <TabsContent value="session">
              <SessionPanel session={session} error={sessionError} onConfigureToken={onConfigureToken} />
            </TabsContent>
            <TabsContent value="tools">
              {open && <ToolsPanel />}
            </TabsContent>
            <TabsContent value="audit">
              <AuditPanel audit={audit} />
            </TabsContent>
            <TabsContent value="model">
              <ModelPanel />
            </TabsContent>
          </div>
        </Tabs>
      </SheetContent>
    </Sheet>
  )
}

function SessionPanel({
  session,
  error,
  onConfigureToken,
}: {
  session?: Session
  error?: unknown
  onConfigureToken: () => void
}) {
  if (error) {
    return (
      <div className="flex flex-col items-start gap-3 rounded-lg border border-warning/30 bg-warning/5 p-4">
        <p className="text-sm font-medium">Session could not be verified</p>
        <p className="text-sm text-muted-foreground">The gateway rejected the current bearer token.</p>
        <Button size="sm" variant="outline" onClick={onConfigureToken}>
          <KeyRound />
          Configure token
        </Button>
      </div>
    )
  }
  if (!session) return <Loader2 className="size-4 animate-spin text-muted-foreground" aria-label="Loading session" />

  return (
    <div className="flex flex-col gap-5">
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-md border bg-border text-xs">
        <Cell label="Subject" value={session.subject} />
        <Cell label="Display name" value={session.display_name ?? '—'} />
        <Cell label="Role" value={session.role ?? '—'} />
        <Cell label="Department" value={session.department ?? '—'} />
      </dl>
      <section className="flex flex-col gap-2">
        <h3 className="text-xs font-medium text-muted-foreground">Permissions</h3>
        <ul className="flex flex-wrap gap-1.5">
          {session.permissions.map((p) => (
            <li key={p}>
              <Badge variant="outline" className="rounded font-mono">
                {p}
              </Badge>
            </li>
          ))}
        </ul>
      </section>
      <section className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-medium text-muted-foreground">Decoded JWT claims</h3>
          <Button size="xs" variant="ghost" onClick={onConfigureToken}>
            <KeyRound />
            Change token
          </Button>
        </div>
        <pre className="scrollbar-thin overflow-x-auto rounded-md border bg-muted/40 p-3 font-mono text-[11.5px] leading-relaxed">
          <JsonView value={session.claims ?? { sub: session.subject, roles: session.permissions }} />
        </pre>
      </section>
    </div>
  )
}

function JsonView({ value }: { value: Record<string, unknown> }) {
  const entries = Object.entries(value)
  return (
    <code>
      {'{\n'}
      {entries.map(([k, v], i) => (
        <span key={k}>
          {'  '}
          <span className="text-muted-foreground">&quot;{k}&quot;</span>
          {': '}
          <span className={typeof v === 'number' ? 'text-warning-foreground' : 'text-verified-foreground'}>
            {JSON.stringify(v)}
          </span>
          {i < entries.length - 1 ? ',' : ''}
          {'\n'}
        </span>
      ))}
      {'}'}
    </code>
  )
}

function ToolsPanel() {
  const { data, error, isLoading } = useSWR('mcp-tools', () => api.tools(), { revalidateOnFocus: false })
  const tools: McpTool[] = data ? (Array.isArray(data.data) ? data.data : data.data.tools) : []

  if (isLoading) return <Loader2 className="size-4 animate-spin text-muted-foreground" aria-label="Loading tools" />
  if (error) return <p className="text-sm text-muted-foreground">Tool registry unavailable.</p>

  return (
    <ul className="flex flex-col gap-2">
      {tools.map((t) => (
        <li key={t.name} className="rounded-md border p-3">
          <div className="flex items-center justify-between gap-2">
            <code className="font-mono text-[13px] font-medium">{t.name}</code>
            <Badge variant="outline" className="rounded font-mono text-verified-foreground">
              read-only
            </Badge>
          </div>
          {t.description && <p className="mt-1 text-xs text-muted-foreground">{t.description}</p>}
          {t.parameters && (
            <dl className="mt-2 flex flex-wrap gap-1.5">
              {Object.entries(t.parameters).map(([k, v]) => (
                <div key={k} className="rounded border bg-muted/40 px-1.5 py-0.5 font-mono text-[10.5px]">
                  <dt className="inline">{k}</dt>
                  <dd className="inline text-muted-foreground">: {v}</dd>
                </div>
              ))}
            </dl>
          )}
        </li>
      ))}
    </ul>
  )
}

const STATUS_STYLES: Record<AuditStatus, string> = {
  allowed: 'text-verified-foreground',
  denied: 'text-destructive',
  throttled: 'text-warning-foreground',
  error: 'text-warning-foreground',
  cancelled: 'text-muted-foreground',
}

function AuditPanel({ audit }: { audit: AuditEvent[] }) {
  return (
    <div className="overflow-hidden rounded-md border">
      <table className="w-full text-xs">
        <thead className="bg-muted/50 text-left text-muted-foreground">
          <tr>
            <th className="px-2.5 py-2 font-medium">Time</th>
            <th className="px-2.5 py-2 font-medium">Event</th>
            <th className="px-2.5 py-2 font-medium">Status</th>
            <th className="px-2.5 py-2 text-right font-medium">Latency</th>
          </tr>
        </thead>
        <tbody className="divide-y font-mono text-[11px]">
          {audit.map((e) => (
            <tr key={e.id} className="align-top">
              <td className="px-2.5 py-2 whitespace-nowrap text-muted-foreground">
                {new Date(e.at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
              </td>
              <td className="px-2.5 py-2">
                <div>{e.event}</div>
                <div className="text-muted-foreground">{e.correlationId}</div>
                {e.detail && <div className="text-muted-foreground">{e.detail}</div>}
              </td>
              <td className={cn('px-2.5 py-2', STATUS_STYLES[e.status])}>{e.status}</td>
              <td className="px-2.5 py-2 text-right tabular-nums">{e.latencyMs}ms</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ModelPanel() {
  return (
    <dl className="grid grid-cols-1 gap-px overflow-hidden rounded-md border bg-border text-xs">
      <Cell label="Inference host" value={MODEL_INFO.host} />
      <Cell label="Model" value={MODEL_INFO.model} />
      <Cell label="Revision" value={MODEL_INFO.revision} />
      <Cell label="Context window" value={`${MODEL_INFO.contextWindow.toLocaleString()} tokens`} />
      <Cell label="Network egress" value="Disabled (air-gapped)" />
    </dl>
  )
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1 bg-background p-2.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="truncate font-mono">{value}</dd>
    </div>
  )
}
