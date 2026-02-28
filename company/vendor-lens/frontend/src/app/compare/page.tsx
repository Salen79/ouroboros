'use client'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { Suspense } from 'react'

type AnalysisResult = {
  id: string
  vendor_name: string
  plans: Array<{ name: string; price_monthly: number | null; features: string[] }>
  risks: string[]
  cost_at_100: number | null
  cost_at_1k: number | null
}

function CompareContent() {
  const params = useSearchParams()
  const ids = params.get('ids')?.split(',') ?? []
  const [results, setResults] = useState<AnalysisResult[]>([])

  useEffect(() => {
    Promise.all(
      ids.map((id) =>
        fetch(`${process.env.NEXT_PUBLIC_API_URL}/analyze/${id}`).then((r) => r.json())
      )
    ).then(setResults)
  }, [ids.join(',')])

  if (!results.length) return <div className="p-8 text-gray-400">Loading…</div>

  return (
    <main className="max-w-6xl mx-auto px-6 py-12">
      <h1 className="text-3xl font-bold mb-8">Side-by-Side Comparison</h1>
      <div className="grid gap-6" style={{ gridTemplateColumns: `repeat(${results.length}, 1fr)` }}>
        {results.map((r) => (
          <div key={r.id} className="bg-white rounded-2xl p-6 border border-gray-200 shadow-sm">
            <h2 className="text-xl font-semibold mb-4">{r.vendor_name}</h2>
            <p className="text-sm text-gray-500 mb-2">Cost @ 100 users: <strong>${r.cost_at_100 ?? '?'}</strong></p>
            <p className="text-sm text-gray-500 mb-4">Cost @ 1k users: <strong>${r.cost_at_1k ?? '?'}</strong></p>
            <h3 className="font-medium mb-2 text-sm text-gray-700">Plans</h3>
            {r.plans.map((p) => (
              <div key={p.name} className="mb-3">
                <p className="font-semibold text-sm">{p.name} — ${p.price_monthly ?? '?'}/mo</p>
              </div>
            ))}
            {r.risks.length > 0 && (
              <>
                <h3 className="font-medium mb-2 text-sm text-amber-700 mt-4">⚠️ Risks</h3>
                <ul className="text-xs text-amber-800 space-y-1">
                  {r.risks.map((risk, i) => <li key={i}>{risk}</li>)}
                </ul>
              </>
            )}
          </div>
        ))}
      </div>
    </main>
  )
}

export default function ComparePage() {
  return (
    <Suspense fallback={<div className="p-8">Loading…</div>}>
      <CompareContent />
    </Suspense>
  )
}
