'use client'

import { AnimatePresence, motion } from 'motion/react'
import type { Inflight } from '@/hooks/use-assistant'
import { ToolTrace } from './tool-trace'

const PHASES = ['Verifying permissions…', 'Searching internal sources…', 'Writing response…']

export function InflightMessage({ inflight }: { inflight: Inflight }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col gap-3"
      aria-live="polite"
      aria-busy
    >
      {inflight.phase >= 1 && <ToolTrace calls={[inflight.toolCall]} />}
      <div className="flex items-center gap-2.5">
        <span className="flex gap-1" aria-hidden>
          {[0, 1, 2].map((i) => (
            <motion.span
              key={i}
              className="size-1.5 rounded-full bg-primary"
              animate={{ opacity: [0.25, 1, 0.25] }}
              transition={{ duration: 1.1, repeat: Infinity, delay: i * 0.16 }}
            />
          ))}
        </span>
        <AnimatePresence mode="wait">
          <motion.span
            key={inflight.phase}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.18 }}
            className="shimmer-text text-sm"
          >
            {PHASES[inflight.phase]}
          </motion.span>
        </AnimatePresence>
      </div>
    </motion.div>
  )
}
