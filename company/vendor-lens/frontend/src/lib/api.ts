// Server-side calls use internal backend URL, client-side use relative path
const BASE =
  typeof window === 'undefined'
    ? (process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8100')
    : ''

export interface AnalysisSummary {
  id: string
  url: string
  status: 'pending' | 'processing' | 'done' | 'failed'
  result?: any
  created_at: string
}

export async function listAnalyses(limit = 12): Promise<AnalysisSummary[]> {
  try {
    const res = await fetch(`${BASE}/api/analyses?limit=${limit}`, {
      cache: 'no-store',
    })
    if (!res.ok) return []
    const data = await res.json()
    return Array.isArray(data) ? data : (data.items ?? [])
  } catch {
    return []
  }
}

export async function getAnalysis(id: string): Promise<AnalysisSummary | null> {
  const res = await fetch(`${BASE}/api/analyses/${id}`, { cache: 'no-store' })
  if (!res.ok) return null
  return res.json()
}

export async function submitAnalysis(url: string): Promise<{ id: string }> {
  const res = await fetch(`${BASE}/api/analyses`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail ?? `HTTP ${res.status}`)
  }
  return res.json()
}

export async function pollAnalysis(id: string, maxWait = 60): Promise<unknown> {
  const deadline = Date.now() + maxWait * 1000
  while (Date.now() < deadline) {
    const data = await getAnalysis(id)
    if (data.status === 'completed' || data.status === 'failed') return data
    await new Promise((r) => setTimeout(r, 2000))
  }
  throw new Error('Timed out waiting for analysis')
}
