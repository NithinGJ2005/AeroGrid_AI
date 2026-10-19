'use client'

import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

const components: Components = {
  h1: ({ children }) => <h3 className="mt-1 mb-3 text-base font-semibold tracking-tight">{children}</h3>,
  h2: ({ children }) => <h3 className="mt-1 mb-3 text-base font-semibold tracking-tight">{children}</h3>,
  h3: ({ children }) => <h3 className="mt-1 mb-3 text-[15px] font-semibold tracking-tight">{children}</h3>,
  p: ({ children }) => <p className="my-3 leading-relaxed first:mt-0 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="my-3 flex list-disc flex-col gap-1.5 pl-5 marker:text-muted-foreground">{children}</ul>,
  ol: ({ children }) => <ol className="my-3 flex list-decimal flex-col gap-1.5 pl-5 marker:font-mono marker:text-xs marker:text-muted-foreground">{children}</ol>,
  li: ({ children }) => <li className="pl-1 leading-relaxed">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
  a: ({ children, href }) => (
    <a href={href} className="underline underline-offset-4" rel="noreferrer noopener">
      {children}
    </a>
  ),
  blockquote: ({ children }) => (
    <blockquote className="my-3 border-l-2 pl-3 text-muted-foreground">{children}</blockquote>
  ),
  code: ({ children, className }) =>
    className ? (
      <code className={className}>{children}</code>
    ) : (
      <code className="rounded border bg-muted px-1 py-px font-mono text-[0.85em]">{children}</code>
    ),
  pre: ({ children }) => (
    <pre className="scrollbar-thin my-3 overflow-x-auto rounded-md border bg-muted/50 p-3 font-mono text-xs">{children}</pre>
  ),
  table: ({ children }) => (
    <div className="scrollbar-thin my-4 overflow-x-auto rounded-md border">
      <table className="w-full border-collapse text-[13px]">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-muted/50">{children}</thead>,
  th: ({ children }) => (
    <th className="border-b px-3 py-2 text-left text-xs font-medium whitespace-nowrap text-muted-foreground">{children}</th>
  ),
  td: ({ children }) => <td className="border-b px-3 py-2 align-top tabular-nums [tr:last-child_&]:border-b-0">{children}</td>,
  hr: () => <hr className="my-4" />,
}

export function Markdown({ content }: { content: string }) {
  return (
    <div className="text-[15px] leading-7 text-foreground">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components} skipHtml>
        {content}
      </ReactMarkdown>
    </div>
  )
}
