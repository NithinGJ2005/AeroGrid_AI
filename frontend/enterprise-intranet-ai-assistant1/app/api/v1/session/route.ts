import { DEMO_SESSION } from '@/lib/demo-backend'

export async function GET(req: Request) {
  const headers = { 'x-correlation-id': req.headers.get('x-correlation-id') ?? crypto.randomUUID() }
  if (req.headers.get('authorization') === 'Bearer invalid') {
    return Response.json({ detail: 'Bearer token missing or expired.' }, { status: 401, headers })
  }
  return Response.json(DEMO_SESSION, { headers })
}
