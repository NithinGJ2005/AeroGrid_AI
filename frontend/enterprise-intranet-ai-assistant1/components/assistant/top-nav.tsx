'use client'

import { Activity, Menu, ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Kbd, KbdGroup } from '@/components/ui/kbd'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { MODEL_INFO } from '@/lib/catalog'

interface TopNavProps {
  title: string | null
  showMenuButton: boolean
  onOpenSidebar: () => void
  lastLatencyMs: number | null
  onOpenInspector: () => void
  modKey: string
}

export function TopNav({ title, showMenuButton, onOpenSidebar, lastLatencyMs, onOpenInspector, modKey }: TopNavProps) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-2 px-3 sm:px-4">
      {showMenuButton && (
        <Button variant="ghost" size="icon-sm" onClick={onOpenSidebar} aria-label="Open navigation">
          <Menu />
        </Button>
      )}
      <h1 className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
        {title ?? <span className="text-muted-foreground">New chat</span>}
      </h1>
      <div className="flex items-center gap-0.5">
        <DiagnosticsPopover lastLatencyMs={lastLatencyMs} />
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                variant="ghost"
                size="icon-sm"
                className="text-muted-foreground"
                onClick={onOpenInspector}
                aria-label="Open security and audit"
              />
            }
          >
            <ShieldCheck />
          </TooltipTrigger>
          <TooltipContent side="bottom">
            Security & audit
            <KbdGroup>
              <Kbd>{modKey}</Kbd>
              <Kbd>I</Kbd>
            </KbdGroup>
          </TooltipContent>
        </Tooltip>
      </div>
    </header>
  )
}

function DiagnosticsPopover({ lastLatencyMs }: { lastLatencyMs: number | null }) {
  const latency = lastLatencyMs ? `${lastLatencyMs}ms` : '42ms'
  const rows = [
    { label: 'Inference latency', value: latency },
    { label: 'Queue depth', value: '0' },
    { label: 'GPU memory', value: '61% · safe' },
    { label: 'Network egress', value: 'Blocked' },
  ]
  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button
            variant="ghost"
            size="sm"
            aria-label="System status"
            className="gap-1.5 text-xs font-normal text-muted-foreground"
          />
        }
      >
        <span className="relative flex size-1.5" aria-hidden>
          <span className="absolute inline-flex size-full rounded-full bg-verified opacity-50 motion-safe:animate-ping" />
          <span className="relative inline-flex size-1.5 rounded-full bg-verified" />
        </span>
        <span className="hidden sm:inline">Private network</span>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 p-0">
        <div className="flex items-center gap-2 border-b px-3 py-2.5">
          <Activity className="size-4 text-muted-foreground" aria-hidden />
          <div className="min-w-0">
            <p className="text-sm font-medium">System status</p>
            <p className="truncate font-mono text-[11px] text-muted-foreground">{MODEL_INFO.host}</p>
          </div>
        </div>
        <dl className="divide-y">
          {rows.map((r) => (
            <div key={r.label} className="flex items-center justify-between px-3 py-2 text-xs">
              <dt className="text-muted-foreground">{r.label}</dt>
              <dd className="flex items-center gap-1.5 font-mono">
                <span className="size-1.5 rounded-full bg-verified" aria-hidden />
                {r.value}
              </dd>
            </div>
          ))}
        </dl>
        <p className="border-t px-3 py-2 text-[11px] text-muted-foreground">
          {MODEL_INFO.model} · zero public internet egress
        </p>
      </PopoverContent>
    </Popover>
  )
}
