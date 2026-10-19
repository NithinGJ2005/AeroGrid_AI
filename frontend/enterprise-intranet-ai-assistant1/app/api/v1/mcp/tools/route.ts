import { DEMO_TOOLS } from '@/lib/demo-backend'

export async function GET(req: Request) {
  const headers = { 'x-correlation-id': req.headers.get('x-correlation-id') ?? crypto.randomUUID() }
  return Response.json({ tools: DEMO_TOOLS }, { headers })
}
