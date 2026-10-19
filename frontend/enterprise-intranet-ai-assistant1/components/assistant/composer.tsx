'use client'

import type { Ref } from 'react'
import { ArrowUp, ChevronDown, FolderSearch, Layers, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { KNOWLEDGE_BASES, MODEL_INFO, SCOPES, estimateTokens } from '@/lib/catalog'
import type { Scope } from '@/lib/types'
import { cn } from '@/lib/utils'

interface ComposerProps {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  onStop: () => void
  isGenerating: boolean
  scope: Scope
  onScopeChange: (scope: Scope) => void
  selectedFolders: string[]
  onToggleFolder: (folder: string) => void
  onClearFolders: () => void
  textareaRef: Ref<HTMLTextAreaElement>
}

const SCOPE_HINTS: Record<Scope, string> = {
  all: 'Documents and catalog data',
  docs: 'Policies, guides, and PDFs',
  sql: 'Approved read-only queries',
}

export function Composer({
  value,
  onChange,
  onSubmit,
  onStop,
  isGenerating,
  scope,
  onScopeChange,
  selectedFolders,
  onToggleFolder,
  onClearFolders,
  textareaRef,
}: ComposerProps) {
  const tokens = estimateTokens(value)
  const limit = MODEL_INFO.contextWindow
  const ratio = tokens / limit
  const overLimit = tokens > limit
  const canSend = value.trim().length > 0 && !overLimit && !isGenerating
  const scopeLabel = SCOPES.find((s) => s.id === scope)?.label ?? 'All Intranet'

  const folderLabel =
    selectedFolders.length === 0
      ? 'All folders'
      : selectedFolders.length === 1
        ? (KNOWLEDGE_BASES.find((k) => k.folder === selectedFolders[0])?.name ?? '1 folder')
        : `${selectedFolders.length} folders`

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (canSend) onSubmit()
      }}
      className="rounded-2xl border bg-background shadow-[0_1px_2px_rgb(0_0_0/0.04),0_4px_16px_-4px_rgb(0_0_0/0.06)] transition-[border-color,box-shadow] focus-within:border-primary/40 focus-within:ring-4 focus-within:ring-primary/10"
    >
      <label htmlFor="composer" className="sr-only">
        Ask anything about your organization
      </label>
      <textarea
        id="composer"
        ref={textareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key !== 'Enter' || e.shiftKey) return
          if (e.nativeEvent.isComposing || e.keyCode === 229) return
          e.preventDefault()
          if (canSend) onSubmit()
        }}
        rows={1}
        placeholder="Ask anything about your organization..."
        className="scrollbar-thin block max-h-60 min-h-14 w-full resize-none bg-transparent px-4 pt-3.5 pb-1 text-[15px] leading-relaxed outline-none [field-sizing:content] placeholder:text-muted-foreground"
      />
      <div className="flex items-center gap-1 px-2 pt-1 pb-2">
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={`Search scope: ${scopeLabel}`}
                className={cn('gap-1.5 text-xs font-normal text-muted-foreground', scope !== 'all' && 'text-primary')}
              />
            }
          >
            <Layers />
            <span className="hidden sm:inline">{scopeLabel}</span>
            <ChevronDown className="size-3 opacity-60" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-60">
            <DropdownMenuGroup>
              <DropdownMenuLabel>Search scope</DropdownMenuLabel>
              <DropdownMenuRadioGroup value={scope} onValueChange={(v) => onScopeChange(v as Scope)}>
                {SCOPES.map((s) => (
                  <DropdownMenuRadioItem key={s.id} value={s.id}>
                    <span className="flex flex-col">
                      <span>{s.label}</span>
                      <span className="text-xs text-muted-foreground">{SCOPE_HINTS[s.id]}</span>
                    </span>
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={`Folder filter: ${folderLabel}`}
                className={cn(
                  'gap-1.5 text-xs font-normal text-muted-foreground',
                  selectedFolders.length > 0 && 'text-primary',
                )}
              />
            }
          >
            <FolderSearch />
            <span className="hidden max-w-36 truncate sm:inline">{folderLabel}</span>
            <ChevronDown className="size-3 opacity-60" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-64">
            <DropdownMenuGroup>
              <DropdownMenuLabel>Restrict document search to</DropdownMenuLabel>
              {KNOWLEDGE_BASES.map((kb) => (
                <DropdownMenuCheckboxItem
                  key={kb.id}
                  checked={selectedFolders.includes(kb.folder)}
                  onCheckedChange={() => onToggleFolder(kb.folder)}
                  closeOnClick={false}
                >
                  <span className="flex flex-col">
                    <span>{kb.name}</span>
                    <span className="font-mono text-[10.5px] text-muted-foreground">{kb.folder}</span>
                  </span>
                </DropdownMenuCheckboxItem>
              ))}
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem disabled={selectedFolders.length === 0} onClick={onClearFolders}>
              Clear filters
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <div className="ml-auto flex items-center gap-3">
          {tokens > 0 && (
            <span
              className={cn(
                'hidden text-xs tabular-nums sm:inline',
                overLimit ? 'text-destructive' : ratio > 0.8 ? 'text-warning-foreground' : 'text-muted-foreground',
              )}
              aria-live="polite"
            >
              {overLimit ? 'Message too long · ' : ''}
              {tokens.toLocaleString()} / {limit.toLocaleString()}
            </span>
          )}
          {isGenerating ? (
            <Button
              type="button"
              size="icon-sm"
              variant="secondary"
              className="rounded-full"
              onClick={onStop}
              aria-label="Stop generating"
            >
              <Square className="size-3 fill-current" />
            </Button>
          ) : (
            <Button type="submit" size="icon-sm" className="rounded-full" disabled={!canSend} aria-label="Send message">
              <ArrowUp />
            </Button>
          )}
        </div>
      </div>
    </form>
  )
}
