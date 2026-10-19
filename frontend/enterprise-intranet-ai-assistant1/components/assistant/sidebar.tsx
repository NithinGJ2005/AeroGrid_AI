'use client'

import { useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { useTheme } from 'next-themes'
import {
  Archive,
  BookOpenText,
  Check,
  ChevronRight,
  CircleHelp,
  Database,
  Moon,
  MoreHorizontal,
  PanelLeft,
  Search,
  ShieldCheck,
  SquarePen,
  Sun,
  Trash2,
  X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Kbd, KbdGroup } from '@/components/ui/kbd'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { APPROVED_QUERIES, KNOWLEDGE_BASES } from '@/lib/catalog'
import type { Conversation, Session } from '@/lib/types'
import { cn } from '@/lib/utils'
import { LogoMark } from './logo-mark'

interface SidebarProps {
  open: boolean
  isDesktop: boolean
  onSetOpen: (open: boolean) => void
  conversations: Conversation[]
  activeId: string | null
  isGenerating: boolean
  selectedFolders: string[]
  modKey: string
  session?: Session
  sessionLoading: boolean
  onNew: () => void
  onSelect: (id: string) => void
  onDelete: (id: string) => void
  onArchive: (id: string) => void
  onToggleFolder: (folder: string) => void
  onRunQuery: (prompt: string) => void
  onOpenInspector: () => void
}

const DAY = 86_400_000
const EXPANDED = 256
const RAIL = 56

function groupConversations(items: Conversation[]) {
  const startOfToday = new Date().setHours(0, 0, 0, 0)
  const groups: { label: string; items: Conversation[] }[] = [
    { label: 'Today', items: [] },
    { label: 'Yesterday', items: [] },
    { label: 'Previous 7 days', items: [] },
    { label: 'Older', items: [] },
  ]
  for (const c of [...items].sort((a, b) => b.updatedAt - a.updatedAt)) {
    if (c.updatedAt >= startOfToday) groups[0].items.push(c)
    else if (c.updatedAt >= startOfToday - DAY) groups[1].items.push(c)
    else if (c.updatedAt >= startOfToday - 7 * DAY) groups[2].items.push(c)
    else groups[3].items.push(c)
  }
  return groups.filter((g) => g.items.length > 0)
}

function initials(name: string) {
  return name
    .split(/\s+/)
    .map((p) => p[0])
    .slice(0, 2)
    .join('')
    .toUpperCase()
}

export function Sidebar(props: SidebarProps) {
  const { open, isDesktop, onSetOpen } = props

  if (isDesktop) {
    return (
      <motion.aside
        aria-label="Workspace navigation"
        initial={false}
        animate={{ width: open ? EXPANDED : RAIL }}
        transition={{ duration: 0.18, ease: 'easeOut' }}
        className="relative h-full shrink-0 overflow-hidden border-r bg-sidebar"
      >
        {open ? <ExpandedSidebar {...props} /> : <RailSidebar {...props} />}
      </motion.aside>
    )
  }

  return (
    <AnimatePresence initial={false}>
      {open && (
        <>
          <motion.div
            key="backdrop"
            className="fixed inset-0 z-30 bg-foreground/20"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            onClick={() => onSetOpen(false)}
            aria-hidden
          />
          <motion.aside
            key="drawer"
            role="dialog"
            aria-modal="true"
            aria-label="Workspace navigation"
            initial={{ x: -EXPANDED - 24 }}
            animate={{ x: 0 }}
            exit={{ x: -EXPANDED - 24 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            onKeyDown={(e) => e.key === 'Escape' && onSetOpen(false)}
            className="fixed inset-y-0 left-0 z-40 w-[min(85vw,280px)] border-r bg-sidebar shadow-xl"
          >
            <ExpandedSidebar {...props} />
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}

function ExpandedSidebar({
  isDesktop,
  onSetOpen,
  conversations,
  activeId,
  isGenerating,
  selectedFolders,
  modKey,
  session,
  sessionLoading,
  onNew,
  onSelect,
  onDelete,
  onArchive,
  onToggleFolder,
  onRunQuery,
  onOpenInspector,
}: SidebarProps) {
  const [query, setQuery] = useState('')
  const needle = query.trim().toLowerCase()
  const visible = conversations.filter((c) => !c.archived && (!needle || c.title.toLowerCase().includes(needle)))
  const archived = conversations.filter((c) => c.archived && (!needle || c.title.toLowerCase().includes(needle)))
  const groups = groupConversations(visible)

  return (
    <div className="flex h-full w-full min-w-0 flex-col">
      <div className="flex h-14 shrink-0 items-center gap-2 px-3">
        <LogoMark className="size-6 shrink-0 text-primary" />
        <span className="flex-1 truncate text-sm font-semibold tracking-tight text-foreground">AeroGrid AI</span>
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                variant="ghost"
                size="icon-sm"
                className="text-muted-foreground"
                onClick={() => onSetOpen(false)}
                aria-label={isDesktop ? 'Collapse sidebar' : 'Close navigation'}
              />
            }
          >
            {isDesktop ? <PanelLeft /> : <X />}
          </TooltipTrigger>
          <TooltipContent side="right">
            {isDesktop ? 'Collapse sidebar' : 'Close'}
            {isDesktop && (
              <KbdGroup>
                <Kbd>{modKey}</Kbd>
                <Kbd>B</Kbd>
              </KbdGroup>
            )}
          </TooltipContent>
        </Tooltip>
      </div>

      <div className="flex flex-col gap-2 px-3 pb-2">
        <Button
          variant="outline"
          className="h-9 w-full justify-between bg-background font-normal shadow-none"
          onClick={onNew}
          disabled={isGenerating}
        >
          <span className="flex items-center gap-2">
            <SquarePen className="text-muted-foreground" />
            New chat
          </span>
          <KbdGroup className="hidden lg:inline-flex">
            <Kbd>{modKey}</Kbd>
            <Kbd>K</Kbd>
          </KbdGroup>
        </Button>
        <div className="relative">
          <Search
            className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <label htmlFor="conversation-search" className="sr-only">
            Search conversations
          </label>
          <input
            id="conversation-search"
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search chats"
            className="h-8 w-full rounded-md border border-transparent bg-transparent pr-2 pl-8 text-[13px] transition-colors outline-none placeholder:text-muted-foreground hover:bg-sidebar-accent focus-visible:border-input focus-visible:bg-background focus-visible:ring-2 focus-visible:ring-ring/25"
          />
        </div>
      </div>

      <nav aria-label="Conversations and resources" className="scrollbar-thin flex-1 overflow-y-auto px-3 pb-3">
        <NavGroup icon={BookOpenText} title="Knowledge" count={selectedFolders.length || undefined}>
          {KNOWLEDGE_BASES.map((kb) => {
            const selected = selectedFolders.includes(kb.folder)
            return (
              <button
                key={kb.id}
                type="button"
                aria-pressed={selected}
                onClick={() => onToggleFolder(kb.folder)}
                title={`${kb.meta} · ${selected ? 'Remove from' : 'Add to'} search filter`}
                className={cn(
                  'flex h-8 w-full items-center gap-2 rounded-md pr-2 pl-8 text-left text-[13px] transition-colors outline-none hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-sidebar-ring',
                  selected ? 'text-foreground' : 'text-sidebar-foreground',
                )}
              >
                <span className="flex-1 truncate">{kb.name}</span>
                {selected ? (
                  <Check className="size-3.5 shrink-0 text-primary" aria-hidden />
                ) : (
                  <span className="text-[11px] tabular-nums text-muted-foreground">{kb.documents}</span>
                )}
              </button>
            )
          })}
        </NavGroup>

        <NavGroup icon={Database} title="Approved queries">
          {APPROVED_QUERIES.map((q) => (
            <button
              key={q.id}
              type="button"
              disabled={isGenerating}
              title={q.prompt}
              onClick={() => onRunQuery(q.prompt)}
              className="flex h-8 w-full items-center rounded-md pr-2 pl-8 text-left text-[13px] text-sidebar-foreground transition-colors outline-none hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-sidebar-ring disabled:pointer-events-none disabled:opacity-50"
            >
              <span className="truncate">{q.name}</span>
            </button>
          ))}
        </NavGroup>

        <div className="mt-4">
          {groups.length === 0 && archived.length === 0 && (
            <p className="px-2 py-1.5 text-xs text-muted-foreground">
              {needle ? 'No matching chats.' : 'No conversations yet.'}
            </p>
          )}
          {groups.map((g) => (
            <section key={g.label} className="mb-3" aria-label={g.label}>
              <h2 className="px-2 pb-1 text-xs font-medium text-muted-foreground">{g.label}</h2>
              <ul className="flex flex-col gap-px">
                {g.items.map((c) => (
                  <ConversationRow
                    key={c.id}
                    conversation={c}
                    active={c.id === activeId}
                    disabled={isGenerating}
                    onSelect={onSelect}
                    onDelete={onDelete}
                    onArchive={onArchive}
                  />
                ))}
              </ul>
            </section>
          ))}
          {archived.length > 0 && (
            <Collapsible>
              <CollapsibleTrigger className="group flex h-7 w-full items-center gap-1.5 rounded-md px-2 text-xs font-medium text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring">
                <ChevronRight className="size-3 transition-transform group-data-[panel-open]:rotate-90" aria-hidden />
                Archived
                <span className="tabular-nums">({archived.length})</span>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <ul className="mt-1 flex flex-col gap-px">
                  {archived.map((c) => (
                    <ConversationRow
                      key={c.id}
                      conversation={c}
                      active={c.id === activeId}
                      disabled={isGenerating}
                      onSelect={onSelect}
                      onDelete={onDelete}
                    />
                  ))}
                </ul>
              </CollapsibleContent>
            </Collapsible>
          )}
        </div>
      </nav>

      <div className="flex flex-col gap-px border-t px-3 py-2">
        <FooterItem icon={ShieldCheck} label="Security & audit" onClick={onOpenInspector} shortcut={[modKey, 'I']} />
        <HelpPopover modKey={modKey}>
          <FooterItemTrigger icon={CircleHelp} label="Help & shortcuts" />
        </HelpPopover>
        <ThemeItem />
        <UserRow session={session} loading={sessionLoading} />
      </div>
    </div>
  )
}

function RailSidebar({ onSetOpen, isGenerating, modKey, session, sessionLoading, onNew, onOpenInspector }: SidebarProps) {
  const name = session?.display_name ?? session?.subject ?? 'User'
  return (
    <div className="flex h-full w-14 flex-col items-center">
      <div className="flex h-14 items-center">
        <RailButton label="Expand sidebar" shortcut={[modKey, 'B']} onClick={() => onSetOpen(true)}>
          <PanelLeft />
        </RailButton>
      </div>
      <div className="flex flex-col items-center gap-1">
        <RailButton label="New chat" shortcut={[modKey, 'K']} onClick={onNew} disabled={isGenerating}>
          <SquarePen />
        </RailButton>
        <RailButton label="Search chats" onClick={() => onSetOpen(true)}>
          <Search />
        </RailButton>
        <RailButton label="Knowledge" onClick={() => onSetOpen(true)}>
          <BookOpenText />
        </RailButton>
        <RailButton label="Approved queries" onClick={() => onSetOpen(true)}>
          <Database />
        </RailButton>
      </div>
      <div className="mt-auto flex flex-col items-center gap-1 pb-3">
        <RailButton label="Security & audit" shortcut={[modKey, 'I']} onClick={onOpenInspector}>
          <ShieldCheck />
        </RailButton>
        <HelpPopover modKey={modKey} side="right">
          <RailTrigger label="Help & shortcuts">
            <CircleHelp />
          </RailTrigger>
        </HelpPopover>
        <RailTheme />
        <Tooltip>
          <TooltipTrigger
            render={
              <div
                tabIndex={0}
                aria-label={`Signed in as ${name}`}
                className="mt-1 flex size-8 items-center justify-center rounded-full bg-primary/10 text-[11px] font-semibold text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            }
          >
            {sessionLoading ? '··' : initials(name)}
          </TooltipTrigger>
          <TooltipContent side="right">{sessionLoading ? 'Verifying session…' : name}</TooltipContent>
        </Tooltip>
      </div>
    </div>
  )
}

function RailButton({
  label,
  shortcut,
  onClick,
  disabled,
  children,
}: {
  label: string
  shortcut?: string[]
  onClick: () => void
  disabled?: boolean
  children: React.ReactNode
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            className="size-9 text-muted-foreground hover:text-foreground"
            aria-label={label}
            onClick={onClick}
            disabled={disabled}
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent side="right">
        {label}
        {shortcut && (
          <KbdGroup>
            {shortcut.map((k) => (
              <Kbd key={k}>{k}</Kbd>
            ))}
          </KbdGroup>
        )}
      </TooltipContent>
    </Tooltip>
  )
}

function RailTrigger({ label, children, ...rest }: { label: string; children: React.ReactNode }) {
  return (
    <Button
      variant="ghost"
      size="icon"
      className="size-9 text-muted-foreground hover:text-foreground"
      aria-label={label}
      title={label}
      {...rest}
    >
      {children}
    </Button>
  )
}

function RailTheme() {
  const { resolvedTheme, setTheme } = useTheme()
  return (
    <RailButton
      label={resolvedTheme === 'dark' ? 'Light mode' : 'Dark mode'}
      onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}
    >
      <Sun className="hidden dark:block" />
      <Moon className="dark:hidden" />
    </RailButton>
  )
}

function NavGroup({
  icon: Icon,
  title,
  count,
  children,
}: {
  icon: React.ElementType
  title: string
  count?: number
  children: React.ReactNode
}) {
  return (
    <Collapsible className="mt-0.5">
      <CollapsibleTrigger className="group flex h-8 w-full items-center gap-2 rounded-md px-2 text-[13px] text-sidebar-foreground transition-colors outline-none hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-sidebar-ring">
        <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        <span className="flex-1 text-left">{title}</span>
        {count !== undefined && (
          <span className="rounded bg-primary/10 px-1.5 text-[11px] font-medium tabular-nums text-primary">
            {count}
          </span>
        )}
        <ChevronRight
          className="size-3.5 text-muted-foreground transition-transform group-data-[panel-open]:rotate-90"
          aria-hidden
        />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="flex flex-col gap-px py-0.5">{children}</div>
      </CollapsibleContent>
    </Collapsible>
  )
}

const footerItemClass =
  'flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-[13px] text-sidebar-foreground transition-colors outline-none hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-sidebar-ring'

function FooterItem({
  icon: Icon,
  label,
  onClick,
  shortcut,
}: {
  icon: React.ElementType
  label: string
  onClick: () => void
  shortcut?: string[]
}) {
  return (
    <button type="button" onClick={onClick} className={cn(footerItemClass, 'group')}>
      <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      <span className="flex-1">{label}</span>
      {shortcut && (
        <KbdGroup className="opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
          {shortcut.map((k) => (
            <Kbd key={k}>{k}</Kbd>
          ))}
        </KbdGroup>
      )}
    </button>
  )
}

function FooterItemTrigger({ icon: Icon, label, ...rest }: { icon: React.ElementType; label: string }) {
  return (
    <button type="button" className={footerItemClass} {...rest}>
      <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      <span className="flex-1">{label}</span>
    </button>
  )
}

function ThemeItem() {
  const { resolvedTheme, setTheme } = useTheme()
  const dark = resolvedTheme === 'dark'
  return (
    <button type="button" onClick={() => setTheme(dark ? 'light' : 'dark')} className={footerItemClass}>
      <Sun className="hidden size-4 shrink-0 text-muted-foreground dark:block" aria-hidden />
      <Moon className="size-4 shrink-0 text-muted-foreground dark:hidden" aria-hidden />
      <span className="flex-1">
        <span className="hidden dark:inline">Light mode</span>
        <span className="dark:hidden">Dark mode</span>
      </span>
    </button>
  )
}

function UserRow({ session, loading }: { session?: Session; loading: boolean }) {
  const name = session?.display_name ?? session?.subject ?? 'Unknown user'
  const role = session?.role ?? session?.permissions[0]
  return (
    <div className="mt-1 flex items-center gap-2.5 rounded-md px-1.5 py-1.5">
      <div
        aria-hidden
        className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[11px] font-semibold text-primary"
      >
        {loading ? '··' : initials(name)}
      </div>
      <div className="flex min-w-0 flex-col leading-tight">
        <span className="truncate text-[13px] font-medium text-foreground">{loading ? 'Verifying session…' : name}</span>
        <span className="truncate text-xs text-muted-foreground">
          {[role, session?.department].filter(Boolean).join(' · ') || '—'}
        </span>
      </div>
    </div>
  )
}

const SHORTCUTS = [
  { label: 'New chat', keys: ['K'] },
  { label: 'Focus composer', keys: ['/'] },
  { label: 'Toggle sidebar', keys: ['B'] },
  { label: 'Security & audit', keys: ['I'] },
]

function HelpPopover({
  modKey,
  side = 'top',
  children,
}: {
  modKey: string
  side?: 'top' | 'right'
  children: React.ReactElement
}) {
  return (
    <Popover>
      <PopoverTrigger render={children} />
      <PopoverContent side={side} align="start" className="w-64 p-0">
        <div className="border-b px-3 py-2.5">
          <p className="text-sm font-medium">Keyboard shortcuts</p>
          <p className="text-xs text-muted-foreground">Answers cite verified intranet sources only.</p>
        </div>
        <dl className="flex flex-col gap-1.5 px-3 py-2.5 text-[13px]">
          {SHORTCUTS.map((s) => (
            <div key={s.label} className="flex items-center justify-between">
              <dt className="text-muted-foreground">{s.label}</dt>
              <dd>
                <KbdGroup>
                  <Kbd>{modKey}</Kbd>
                  {s.keys.map((k) => (
                    <Kbd key={k}>{k}</Kbd>
                  ))}
                </KbdGroup>
              </dd>
            </div>
          ))}
          <div className="flex items-center justify-between">
            <dt className="text-muted-foreground">Stop generating</dt>
            <dd>
              <Kbd>Esc</Kbd>
            </dd>
          </div>
        </dl>
      </PopoverContent>
    </Popover>
  )
}

function ConversationRow({
  conversation,
  active,
  disabled,
  onSelect,
  onDelete,
  onArchive,
}: {
  conversation: Conversation
  active: boolean
  disabled: boolean
  onSelect: (id: string) => void
  onDelete: (id: string) => void
  onArchive?: (id: string) => void
}) {
  const triggerRef = useRef<HTMLButtonElement>(null)
  return (
    <li className="group/row relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => onSelect(conversation.id)}
        aria-current={active ? 'page' : undefined}
        className={cn(
          'flex h-8 w-full items-center rounded-md pr-8 pl-2 text-left text-[13px] transition-colors outline-none hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-sidebar-ring disabled:cursor-not-allowed',
          active ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground' : 'text-sidebar-foreground',
        )}
      >
        <span className="truncate">{conversation.title}</span>
      </button>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              ref={triggerRef}
              variant="ghost"
              size="icon-xs"
              aria-label={`Options for ${conversation.title}`}
              className="absolute top-1/2 right-1 -translate-y-1/2 text-muted-foreground opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100 aria-expanded:opacity-100"
            />
          }
        >
          <MoreHorizontal />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-40">
          {onArchive && (
            <>
              <DropdownMenuItem onClick={() => onArchive(conversation.id)}>
                <Archive />
                Archive
              </DropdownMenuItem>
              <DropdownMenuSeparator />
            </>
          )}
          <DropdownMenuItem variant="destructive" onClick={() => onDelete(conversation.id)}>
            <Trash2 />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </li>
  )
}
