'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { getAuthToken, setAuthToken } from '@/lib/api'

interface TokenDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: () => void
}

export function TokenDialog({ open, onOpenChange, onSaved }: TokenDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        {open && <TokenForm onDone={(changed) => (changed && onSaved(), onOpenChange(false))} />}
      </DialogContent>
    </Dialog>
  )
}

function TokenForm({ onDone }: { onDone: (changed: boolean) => void }) {
  const [value, setValue] = useState(() => getAuthToken() ?? '')

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        setAuthToken(value.trim() || null)
        onDone(true)
      }}
      className="flex flex-col gap-4"
    >
      <DialogHeader>
        <DialogTitle>Intranet bearer token</DialogTitle>
        <DialogDescription>
          Sent as <code className="font-mono text-xs">Authorization: Bearer</code> on every gateway request. Stored in
          this tab&apos;s session storage only and cleared when the tab closes.
        </DialogDescription>
      </DialogHeader>
      <div className="flex flex-col gap-1.5">
        <label htmlFor="bearer" className="text-xs font-medium">
          Token
        </label>
        <input
          id="bearer"
          type="password"
          autoComplete="off"
          spellCheck={false}
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="eyJhbGciOiJSUzI1NiIs…"
          className="h-9 rounded-md border bg-background px-3 font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
      </div>
      <DialogFooter>
        <Button
          type="button"
          variant="ghost"
          onClick={() => {
            setAuthToken(null)
            onDone(true)
          }}
        >
          Clear
        </Button>
        <Button type="submit">Save token</Button>
      </DialogFooter>
    </form>
  )
}
