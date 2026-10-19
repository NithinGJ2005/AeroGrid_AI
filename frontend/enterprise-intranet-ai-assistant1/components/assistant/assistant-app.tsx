'use client'

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import useSWR from 'swr'
import { useAssistant } from '@/hooks/use-assistant'
import { useModKey } from '@/hooks/use-mod-key'
import { api } from '@/lib/api'
import type { Citation, Scope } from '@/lib/types'
import { CitationSheet } from './citation-sheet'
import { Composer } from './composer'
import { InflightMessage } from './inflight-message'
import { InspectorSheet } from './inspector-sheet'
import { AssistantMessage, UserMessage } from './message'
import { Sidebar } from './sidebar'
import { TokenDialog } from './token-dialog'
import { TopNav } from './top-nav'
import { WelcomeState } from './welcome-state'

const DESKTOP_QUERY = '(min-width: 1024px)'

function useIsDesktop() {
  return useSyncExternalStore(
    (cb) => {
      const mql = window.matchMedia(DESKTOP_QUERY)
      mql.addEventListener('change', cb)
      return () => mql.removeEventListener('change', cb)
    },
    () => window.matchMedia(DESKTOP_QUERY).matches,
    () => true,
  )
}

export function AssistantApp() {
  const isDesktop = useIsDesktop()
  const modKey = useModKey()
  const [sidebarPref, setSidebarPref] = useState<boolean | null>(null)
  const sidebarOpen = sidebarPref ?? isDesktop
  const [scope, setScope] = useState<Scope>('all')
  const [folders, setFolders] = useState<string[]>([])
  const [draft, setDraft] = useState('')
  const [citation, setCitation] = useState<Citation | null>(null)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [tokenOpen, setTokenOpen] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  const session = useSWR('session', () => api.session(), { revalidateOnFocus: false, shouldRetryOnError: false })

  const openTokenDialog = useCallback(() => setTokenOpen(true), [])
  const assistant = useAssistant({ onUnauthorized: openTokenDialog })
  const { active, inflight, isGenerating } = assistant
  const messages = active?.messages ?? []
  const showInflight = inflight && inflight.conversationId === active?.id

  const closeSidebarOnMobile = () => {
    if (!isDesktop) setSidebarPref(false)
  }

  const submit = useCallback(
    (text: string, nextScope: Scope = scope, fresh = false) => {
      if (!text.trim() || isGenerating) return
      assistant.send({ text, scope: nextScope, folders, author: session.data?.data.display_name, fresh })
      setDraft('')
    },
    [assistant, folders, isGenerating, scope, session.data],
  )

  const retryLast = () => {
    const lastUser = [...messages].reverse().find((m) => m.role === 'user')
    if (lastUser) submit(lastUser.content, lastUser.scope)
  }

  const toggleFolder = (folder: string) =>
    setFolders((prev) => (prev.includes(folder) ? prev.filter((f) => f !== folder) : [...prev, folder]))

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length, inflight?.phase, active?.id])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey
      if (mod && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        assistant.newConversation()
        textareaRef.current?.focus()
      } else if (mod && e.key.toLowerCase() === 'b') {
        e.preventDefault()
        setSidebarPref((p) => !(p ?? isDesktop))
      } else if (mod && e.key.toLowerCase() === 'i') {
        e.preventDefault()
        setInspectorOpen((o) => !o)
      } else if (mod && e.key === '/') {
        e.preventDefault()
        textareaRef.current?.focus()
      } else if (e.key === 'Escape' && isGenerating) {
        assistant.stop()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [assistant, isDesktop, isGenerating])

  return (
    <div className="flex h-dvh overflow-hidden bg-background">
        <Sidebar
          open={sidebarOpen}
          isDesktop={isDesktop}
          onSetOpen={setSidebarPref}
          conversations={assistant.conversations}
          activeId={assistant.activeId}
          isGenerating={isGenerating}
          selectedFolders={folders}
          modKey={modKey}
          session={session.data?.data}
          sessionLoading={session.isLoading}
          onOpenInspector={() => {
            closeSidebarOnMobile()
            setInspectorOpen(true)
          }}
          onNew={() => {
            assistant.newConversation()
            closeSidebarOnMobile()
            textareaRef.current?.focus()
          }}
          onSelect={(id) => {
            assistant.selectConversation(id)
            closeSidebarOnMobile()
          }}
          onDelete={assistant.deleteConversation}
          onArchive={assistant.archiveConversation}
          onToggleFolder={toggleFolder}
          onRunQuery={(prompt) => {
            setScope('sql')
            closeSidebarOnMobile()
            submit(prompt, 'sql', true)
          }}
        />

        <main className="flex min-w-0 flex-1 flex-col">
          <TopNav
            title={messages.length > 0 ? (active?.title ?? null) : null}
            showMenuButton={!isDesktop}
            onOpenSidebar={() => setSidebarPref(true)}
            lastLatencyMs={assistant.lastLatencyMs}
            onOpenInspector={() => setInspectorOpen(true)}
            modKey={modKey}
          />
          <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
            {messages.length === 0 && !showInflight ? (
              <WelcomeState
                onPick={(prompt, s) => {
                  setScope(s)
                  submit(prompt, s)
                }}
              />
            ) : (
              <div className="mx-auto flex w-full max-w-3xl flex-col gap-10 px-4 pt-4 pb-10 sm:px-6">
                <h2 className="sr-only">{active?.title ?? 'Conversation'}</h2>
                {messages.map((m, i) =>
                  m.role === 'user' ? (
                    <UserMessage key={m.id} message={m} />
                  ) : (
                    <AssistantMessage
                      key={m.id}
                      message={m}
                      onOpenCitation={setCitation}
                      onConfigureToken={openTokenDialog}
                      onRetry={i === messages.length - 1 && !isGenerating ? retryLast : undefined}
                    />
                  ),
                )}
                {showInflight && <InflightMessage inflight={inflight} />}
                <div ref={bottomRef} className="h-px" aria-hidden />
              </div>
            )}
          </div>

          <div className="px-4 pt-1 pb-3 sm:px-6">
            <div className="mx-auto w-full max-w-3xl">
              <Composer
                value={draft}
                onChange={setDraft}
                onSubmit={() => submit(draft)}
                onStop={assistant.stop}
                isGenerating={isGenerating}
                scope={scope}
                onScopeChange={setScope}
                selectedFolders={folders}
                onToggleFolder={toggleFolder}
                onClearFolders={() => setFolders([])}
                textareaRef={textareaRef}
              />
              <p className="mt-2 text-center text-xs text-muted-foreground">
                Answers come only from verified internal sources. Requests are audited.
              </p>
            </div>
          </div>
        </main>

      <CitationSheet citation={citation} onOpenChange={(o) => !o && setCitation(null)} />
      <InspectorSheet
        open={inspectorOpen}
        onOpenChange={setInspectorOpen}
        session={session.data?.data}
        sessionError={session.error}
        audit={assistant.audit}
        onConfigureToken={openTokenDialog}
      />
      <TokenDialog open={tokenOpen} onOpenChange={setTokenOpen} onSaved={() => session.mutate()} />
    </div>
  )
}
