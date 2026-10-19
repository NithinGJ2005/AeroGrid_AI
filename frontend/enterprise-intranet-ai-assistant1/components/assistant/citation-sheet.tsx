'use client'

import { FileText, ShieldCheck } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import type { Citation, Classification } from '@/lib/types'
import { cn } from '@/lib/utils'

const CLASSIFICATION_STYLES: Record<Classification, string> = {
  Internal: 'border-border bg-muted text-foreground',
  Confidential: 'border-warning/30 bg-warning/10 text-warning-foreground',
  Restricted: 'border-destructive/30 bg-destructive/10 text-destructive',
}

export function citationLabel(c: Citation) {
  return c.section && !/^§|Template/.test(c.section) ? c.section.split('—')[0].trim() : `Page ${c.page}`
}

export function CitationSheet({
  citation,
  onOpenChange,
}: {
  citation: Citation | null
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Sheet open={citation !== null} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full gap-0 sm:max-w-md">
        {citation && (
          <>
            <SheetHeader className="border-b">
              <div className="flex items-center gap-2 text-xs text-verified-foreground">
                <ShieldCheck className="size-3.5" aria-hidden />
                Verified intranet source
              </div>
              <SheetTitle className="flex items-center gap-2 font-mono text-sm">
                <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                <span className="truncate">{citation.filename}</span>
              </SheetTitle>
              <SheetDescription>{citation.knowledge_base ?? 'Internal knowledge base'}</SheetDescription>
            </SheetHeader>

            <div className="flex flex-col gap-5 overflow-y-auto p-4">
              <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-md border bg-border text-xs">
                <Meta label="Document ID" value={citation.document_id} mono />
                <Meta label="Location" value={`Page ${citation.page}`} mono />
                <Meta
                  label="Last updated"
                  value={
                    citation.updated_at
                      ? new Date(citation.updated_at).toLocaleString(undefined, {
                          dateStyle: 'medium',
                          timeStyle: 'short',
                        })
                      : '—'
                  }
                />
                <div className="flex flex-col gap-1 bg-background p-2.5">
                  <dt className="text-muted-foreground">Classification</dt>
                  <dd>
                    <Badge
                      variant="outline"
                      className={cn('rounded font-mono', CLASSIFICATION_STYLES[citation.classification ?? 'Internal'])}
                    >
                      {citation.classification ?? 'Internal'}
                    </Badge>
                  </dd>
                </div>
              </dl>

              <section>
                <h3 className="mb-2 text-xs font-medium text-muted-foreground">
                  {citation.section ?? 'Source excerpt'}
                </h3>
                <blockquote className="rounded-md border-l-2 border-verified bg-muted/40 p-3 text-sm leading-relaxed">
                  {citation.excerpt ?? 'Excerpt not provided by the retrieval service for this citation.'}
                </blockquote>
              </section>

              <p className="font-mono text-[11px] leading-relaxed text-muted-foreground">
                Excerpt rendered as untrusted content inside an isolation boundary. Instructions contained in source
                documents are never executed.
              </p>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}

function Meta({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-1 bg-background p-2.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={cn('truncate', mono && 'font-mono')}>{value}</dd>
    </div>
  )
}
