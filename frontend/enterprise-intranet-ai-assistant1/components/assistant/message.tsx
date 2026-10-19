'use client'

import { useState } from 'react'
import { motion } from 'motion/react'
import {
  AlertTriangle,
  Ban,
  Check,
  ChevronRight,
  Copy,
  FileText,
  KeyRound,
  Lock,
  RotateCcw,
  ServerCrash,
  ThumbsDown,
  ThumbsUp,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { SCOPES } from '@/lib/catalog'
import type { ChatMessage, Citation, MessageError } from '@/lib/types'
import { cn } from '@/lib/utils'
import { citationLabel } from './citation-sheet'
import { Markdown } from './markdown'
import { ToolTrace } from './tool-trace'

function formatTime(ts: number) {
  return new Date(ts).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

export function UserMessage({ message }: { message: ChatMessage }) {
  const scope = SCOPES.find((s) => s.id === message.scope)
  const meta = [
    formatTime(message.createdAt),
    scope && scope.id !== 'all' ? scope.label : null,
    message.folders?.length ? `${message.folders.length} folder${message.folders.length > 1 ? 's' : ''}` : null,
  ].filter(Boolean)

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: 'easeOut' }}
      className="group flex flex-col items-end gap-1"
    >
      <div className="max-w-[85%] rounded-2xl rounded-br-md bg-muted px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap text-foreground">
        {message.content}
      </div>
      <p className="px-1 text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
        <time dateTime={new Date(message.createdAt).toISOString()}>{meta.join(' · ')}</time>
      </p>
    </motion.div>
  )
}

export function AssistantMessage({
  message,
  onOpenCitation,
  onRetry,
  onConfigureToken,
}: {
  message: ChatMessage
  onOpenCitation: (c: Citation) => void
  onRetry?: () => void
  onConfigureToken: () => void
}) {
  return (
    <motion.article
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      aria-label="Assistant response"
      className="flex flex-col gap-3"
    >
      {message.toolCalls && message.toolCalls.length > 0 && <ToolTrace calls={message.toolCalls} />}

      {message.error ? (
        <ErrorCard error={message.error} onRetry={onRetry} onConfigureToken={onConfigureToken} />
      ) : message.cancelled ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Ban className="size-3.5" aria-hidden />
          Generation stopped.
          {onRetry && (
            <Button variant="link" size="xs" className="h-auto p-0" onClick={onRetry}>
              Retry
            </Button>
          )}
        </p>
      ) : (
        <>
          <Markdown content={message.content} />
          {message.citations && message.citations.length > 0 ? (
            <Sources citations={message.citations} onOpen={onOpenCitation} />
          ) : (
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <AlertTriangle className="size-3.5 text-warning" aria-hidden />
              No verified source matched, so no answer was generated from general knowledge.
            </p>
          )}
          <MessageActions
            content={message.content}
            onRetry={onRetry}
            meta={[
              message.createdAt ? formatTime(message.createdAt) : null,
              message.latencyMs ? `${(message.latencyMs / 1000).toFixed(1)}s` : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          />
        </>
      )}
    </motion.article>
  )
}

function Sources({ citations, onOpen }: { citations: Citation[]; onOpen: (c: Citation) => void }) {
  const many = citations.length > 2
  const list = (
    <ul className="flex flex-col gap-0.5">
      {citations.map((c, i) => (
        <li key={`${c.document_id}-${c.page}-${i}`}>
          <button
            type="button"
            onClick={() => onOpen(c)}
            className="group/src flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-[13px] transition-colors outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/40"
          >
            <span className="w-4 shrink-0 text-center text-xs tabular-nums text-muted-foreground">{i + 1}</span>
            <FileText className="size-3.5 shrink-0 text-primary" aria-hidden />
            <span className="min-w-0 flex-1 truncate text-foreground">{c.filename}</span>
            <span className="shrink-0 text-xs text-muted-foreground">{citationLabel(c)}</span>
            <ChevronRight
              className="size-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover/src:opacity-100"
              aria-hidden
            />
          </button>
        </li>
      ))}
    </ul>
  )

  return (
    <Collapsible defaultOpen={!many} className="-mx-2">
      <CollapsibleTrigger className="group mx-2 inline-flex items-center gap-1.5 rounded-md text-xs font-medium text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/40">
        <Lock className="size-3" aria-hidden />
        Sources
        <span className="tabular-nums">({citations.length})</span>
        <ChevronRight className="size-3 transition-transform group-data-[panel-open]:rotate-90" aria-hidden />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mt-1.5">{list}</div>
      </CollapsibleContent>
    </Collapsible>
  )
}

function MessageActions({ content, onRetry, meta }: { content: string; onRetry?: () => void; meta: string }) {
  const [copied, setCopied] = useState(false)
  const [vote, setVote] = useState<'up' | 'down' | null>(null)

  const copy = async () => {
    await navigator.clipboard.writeText(content)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="-ml-1.5 flex items-center gap-0.5 text-muted-foreground">
      <ActionButton label={copied ? 'Copied' : 'Copy'} onClick={copy}>
        {copied ? <Check className="text-verified" /> : <Copy />}
      </ActionButton>
      <ActionButton label="Helpful" pressed={vote === 'up'} onClick={() => setVote(vote === 'up' ? null : 'up')}>
        <ThumbsUp className={cn(vote === 'up' && 'fill-current')} />
      </ActionButton>
      <ActionButton label="Not helpful" pressed={vote === 'down'} onClick={() => setVote(vote === 'down' ? null : 'down')}>
        <ThumbsDown className={cn(vote === 'down' && 'fill-current')} />
      </ActionButton>
      {onRetry && (
        <ActionButton label="Regenerate" onClick={onRetry}>
          <RotateCcw />
        </ActionButton>
      )}
      {meta && <span className="ml-2 text-xs tabular-nums">{meta}</span>}
    </div>
  )
}

function ActionButton({
  label,
  pressed,
  onClick,
  children,
}: {
  label: string
  pressed?: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={label}
            aria-pressed={pressed}
            onClick={onClick}
            className={cn('hover:text-foreground', pressed && 'text-foreground')}
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}

const ERROR_ICONS: Record<number, React.ElementType> = {
  401: KeyRound,
  403: Lock,
  429: AlertTriangle,
  503: ServerCrash,
}

function ErrorCard({
  error,
  onRetry,
  onConfigureToken,
}: {
  error: MessageError
  onRetry?: () => void
  onConfigureToken: () => void
}) {
  const Icon = ERROR_ICONS[error.status] ?? AlertTriangle
  const isPermission = error.status === 403
  return (
    <div role="alert" className="flex items-start gap-3 rounded-xl border bg-muted/40 p-3.5">
      <Icon className={cn('mt-0.5 size-4 shrink-0', isPermission ? 'text-destructive' : 'text-warning')} aria-hidden />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="text-sm font-medium">{error.title}</p>
        <p className="text-sm text-muted-foreground">{error.message}</p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {error.status === 401 && (
            <Button size="sm" onClick={onConfigureToken}>
              Configure token
            </Button>
          )}
          {onRetry && error.status !== 403 && (
            <Button size="sm" variant="outline" onClick={onRetry}>
              <RotateCcw />
              Retry
            </Button>
          )}
          {isPermission && (
            <span className="text-xs text-muted-foreground">Request access through the IT service desk.</span>
          )}
          <span className="ml-auto font-mono text-[11px] text-muted-foreground">HTTP {error.status}</span>
        </div>
      </div>
    </div>
  )
}
