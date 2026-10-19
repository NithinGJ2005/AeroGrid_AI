'use client'

import { CheckCircle2, ChevronRight, CircleX, Loader2 } from 'lucide-react'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { ToolCall } from '@/lib/types'
import { cn } from '@/lib/utils'

function formatArgs(args: ToolCall['args']) {
  return Object.entries(args)
    .map(([k, v]) => `${k}=${typeof v === 'string' ? `"${v}"` : v}`)
    .join(', ')
}

function describe(call: ToolCall) {
  return call.tool === 'query_database' ? 'Queried the internal catalog' : 'Searched internal documents'
}

export function ToolTrace({ calls, defaultOpen = false }: { calls: ToolCall[]; defaultOpen?: boolean }) {
  const running = calls.some((c) => c.status === 'running')
  const failed = calls.some((c) => c.status === 'error')
  const totalMs = calls.reduce((sum, c) => sum + (c.durationMs ?? 0), 0)
  const label = running ? 'Working…' : failed ? 'Tool call halted' : describe(calls[0])

  return (
    <Collapsible defaultOpen={defaultOpen || running}>
      <CollapsibleTrigger className="group -ml-1 inline-flex items-center gap-1.5 rounded-md px-1 py-0.5 text-[13px] text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/40">
        <StatusIcon status={running ? 'running' : failed ? 'error' : 'complete'} />
        <span>{label}</span>
        {!running && totalMs > 0 && <span className="tabular-nums opacity-70">· {totalMs}ms</span>}
        <ChevronRight className="size-3.5 transition-transform group-data-[panel-open]:rotate-90" aria-hidden />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ol className="mt-2 flex flex-col gap-2 border-l pl-3">
          {calls.map((call, i) => (
            <li key={i} className="flex flex-col gap-1">
              <code className="scrollbar-thin block overflow-x-auto font-mono text-[11.5px] whitespace-nowrap text-foreground/80">
                {call.tool}({formatArgs(call.args)})
              </code>
              <p className="text-xs leading-relaxed text-muted-foreground">
                {call.detail}
                {call.status === 'complete' && call.summary && (
                  <span className="text-foreground/80"> — {call.summary}</span>
                )}
              </p>
            </li>
          ))}
        </ol>
      </CollapsibleContent>
    </Collapsible>
  )
}

function StatusIcon({ status }: { status: ToolCall['status'] }) {
  const cls = 'size-3.5 shrink-0'
  if (status === 'running') return <Loader2 className={cn(cls, 'animate-spin')} aria-label="Running" />
  if (status === 'error') return <CircleX className={cn(cls, 'text-warning')} aria-label="Halted" />
  return <CheckCircle2 className={cn(cls, 'text-verified')} aria-label="Complete" />
}
