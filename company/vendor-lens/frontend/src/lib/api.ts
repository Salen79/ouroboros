const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8002'

export async function submitAnalysis(url: string): Promise<{ id: string }> {
  const res = await fetch(`${BASE}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
  if (!res.ok) throw new Error((await res.json()).detail ?? 'Failed')
  return res.json()
}

export async function getAnalysis(id: string) {
  const res = await fetch(`${BASE}/analyze/${id}`)
  if (!res.ok) throw new Error('Not found')
  return res.json()
}

export async function getComparison(ids: string[]) {
  const res = await fetch(`${BASE}/compare?ids=${ids.join(',')}`)
  if (!res.ok) throw new Error('Failed')
  return res.json()
}
