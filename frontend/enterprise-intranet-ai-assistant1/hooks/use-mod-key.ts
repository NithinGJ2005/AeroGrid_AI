'use client'

import { useSyncExternalStore } from 'react'

const subscribe = () => () => {}

export function useModKey() {
  return useSyncExternalStore(
    subscribe,
    () => (/Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl'),
    () => 'Ctrl',
  )
}
