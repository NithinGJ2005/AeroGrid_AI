import { resolveDemoAnswer } from '@/lib/demo-backend'

const SIMULATED = new Map<number, string>([
  [401, 'Bearer token missing or expired.'],
  [403, 'Missing role for this document/database.'],
  [429, 'Local GPU at capacity.'],
  [503, 'Local inference service offline.'],
])

function sleep(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms)
    signal.addEventListener('abort', () => {
      clearTimeout(t)
      reject(new DOMException('Aborted', 'AbortError'))
    })
  })
}

export async function POST(req: Request) {
  const correlationId = req.headers.get('x-correlation-id') ?? crypto.randomUUID()
  const headers = { 'x-correlation-id': correlationId }

  let message = ''
  try {
    const body = (await req.json()) as { message?: unknown }
    message = typeof body.message === 'string' ? body.message.trim() : ''
  } catch {}

  if (!message || message.length > 16000) {
    return Response.json({ detail: 'Invalid message.' }, { status: 422, headers })
  }

  const simulate = message.match(/^\/simulate\s+(\d{3})/)
  if (simulate) {
    const status = Number(simulate[1])
    if (SIMULATED.has(status)) {
      await sleep(600, req.signal).catch(() => null)
      return Response.json({ detail: SIMULATED.get(status) }, { status, headers })
    }
  }

  if (req.headers.get('authorization') === 'Bearer invalid') {
    return Response.json({ detail: SIMULATED.get(401) }, { status: 401, headers })
  }

  try {
    await sleep(2400 + Math.random() * 800, req.signal)
  } catch {
    return new Response(null, { status: 499, headers })
  }

  return Response.json(resolveDemoAnswer(message), { headers })
}
