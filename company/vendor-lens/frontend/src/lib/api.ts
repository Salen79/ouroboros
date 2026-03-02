const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8100'

export async function submitAnalysis(url: string): Promise<{ id: string }> {
  const res = await fetch(`${BASE}/api/analyses`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
  if (!res.ok) throw new Error((await res.json()).detail ?? 'Failed')
  return res.json()
}

export async function getAnalysis(id: string) {
  const res = await fetch(`${BASE}/api/analyses/${id}`)
  if (!res.ok) throw new Error('Not found')
  return res.json()
}

export async function getComparison(ids: string[]) {
  const res = await fetch(`${BASE}/api/comparisons`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ analysis_ids: ids }),
  })
  if (!res.ok) throw new Error('Failed')
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
