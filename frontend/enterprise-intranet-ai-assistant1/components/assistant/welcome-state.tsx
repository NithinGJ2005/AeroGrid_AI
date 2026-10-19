'use client'

import { motion } from 'motion/react'
import { FileSearch, FolderSearch, ScrollText, Workflow } from 'lucide-react'
import { QUICK_PROMPTS } from '@/lib/catalog'
import type { Scope } from '@/lib/types'

const ICONS = [ScrollText, FileSearch, FolderSearch, Workflow]

export function WelcomeState({ onPick }: { onPick: (prompt: string, scope: Scope) => void }) {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col px-4 pt-[14vh] pb-8 sm:px-6">
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: 'easeOut' }}
        className="flex flex-col items-center text-center"
      >
        <h2 className="text-2xl font-semibold tracking-tight text-balance text-foreground sm:text-[28px]">
          How can I help you today?
        </h2>
        <p className="mt-2 max-w-md text-[15px] leading-relaxed text-pretty text-muted-foreground">
          {"Ask questions about your organization's knowledge, documents, policies, and internal resources."}
        </p>
      </motion.div>

      <ul className="mt-10 grid grid-cols-1 gap-2.5 sm:grid-cols-2" aria-label="Suggested prompts">
        {QUICK_PROMPTS.map((q, i) => {
          const Icon = ICONS[i % ICONS.length]
          return (
            <motion.li
              key={q.prompt}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25, delay: 0.06 + i * 0.04, ease: 'easeOut' }}
            >
              <button
                type="button"
                onClick={() => onPick(q.prompt, q.scope)}
                className="flex h-full w-full items-start gap-3 rounded-xl border bg-background p-3.5 text-left transition-colors outline-none hover:border-primary/30 hover:bg-primary/[0.03] focus-visible:ring-2 focus-visible:ring-ring/40"
              >
                <Icon className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="text-sm font-medium text-foreground">{q.title}</span>
                  <span className="text-[13px] leading-snug text-muted-foreground">{q.prompt}</span>
                </span>
              </button>
            </motion.li>
          )
        })}
      </ul>
    </div>
  )
}
