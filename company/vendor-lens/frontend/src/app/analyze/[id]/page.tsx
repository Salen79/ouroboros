'use client'
import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import CompareButton from '@/components/CompareButton'

type Plan = {
  name: string
  price_monthly: number | null
  price_annual: number | null
  price_unit: string | null
  features: string[]
  limits: Record<string, string>
}

type AnalysisResult = {
  id: string
  url: string
  vendor_name: string
  summary: string
  plans: Plan[]
  cost_at_100: number | null
  cost_at_1k: number | null
  cost_at_10k: number | null
  risks: string[]
  missing_info: string[]
  status: 'pending' | 'processing' | 'done' | 'failed'
  created_at: string
}

export default function AnalysisPage() {
  const { id } = useParams<{ id: string }>()
  const [data, setData] = useState<AnalysisResult | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let timer: NodeJS.Timeout
    async function poll() {
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/analyze/${id}`)
        if (!res.ok) throw new Error('Not found')
        const json: AnalysisResult = await res.json()
        setData(json)
        if (json.status === 'pending' || json.status === 'processing') {
          timer = setTimeout(poll, 2000)
        }
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : 'Failed to load')
      }
    }
    poll()
    return () => clearTimeout(timer)
  }, [id])

  if (error) return <div className="p-8 text-red-500">{error}</div>
  if (!data) return <div className="p-8 text-gray-400">Loading…</div>

  if (data.status === 'pending' || data.status === 'processing') {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-blue-500 border-t-transparent" />
        <p className="text-gray-500">Analyzing {data.url}…</p>
      </div>
    )
  }

  if (data.status === 'failed') {
    return <div className="p-8 text-red-500">Analysis failed. Please try another URL.</div>
  }

  return (
    <main className="max-w-4xl mx-auto px-6 py-12">
      <div className="flex items-start justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">{data.vendor_name}</h1>
          <a href={data.url} target="_blank" rel="noopener noreferrer" className="text-blue-500 text-sm hover:underline">{data.url}</a>
        </div>
        <CompareButton analysisId={data.id} vendorName={data.vendor_name} />
      </div>

      <p className="text-gray-600 mb-8 text-lg">{data.summary}</p>

      {/* Plans */}
      <section className="mb-8">
        <h2 className="text-xl font-semibold mb-4">Pricing Plans</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {data.plans.map((plan) => (
            <div key={plan.name} className="bg-white rounded-2xl p-5 border border-gray-200 shadow-sm">
              <h3 className="font-semibold text-gray-900 mb-1">{plan.name}</h3>
              {plan.price_monthly !== null && (
                <p className="text-2xl font-bold text-blue-600 mb-3">
                  ${plan.price_monthly}<span className="text-sm font-normal text-gray-500">/mo</span>
                </p>
              )}
              {plan.price_unit && <p className="text-sm text-gray-500 mb-2">or {plan.price_unit}</p>}
              <ul className="text-sm text-gray-600 space-y-1">
                {plan.features.slice(0, 4).map((f, i) => <li key={i}>✓ {f}</li>)}
              </ul>
            </div>
          ))}
        </div>
      </section>

      {/* Cost projections */}
      {(data.cost_at_100 || data.cost_at_1k || data.cost_at_10k) && (
        <section className="mb-8 bg-blue-50 rounded-2xl p-6">
          <h2 className="text-xl font-semibold mb-4">Cost Projections</h2>
          <div className="grid grid-cols-3 gap-4 text-center">
            {[['100 users', data.cost_at_100], ['1k users', data.cost_at_1k], ['10k users', data.cost_at_10k]].map(([label, val]) => (
              <div key={label as string}>
                <p className="text-2xl font-bold text-gray-900">${val ?? '?'}</p>
                <p className="text-sm text-gray-500">{label}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Risks */}
      {data.risks.length > 0 && (
        <section className="mb-8">
          <h2 className="text-xl font-semibold mb-4">⚠️ Risk Flags</h2>
          <ul className="space-y-2">
            {data.risks.map((r, i) => (
              <li key={i} className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-xl p-3 text-sm text-amber-900">
                <span>⚠️</span>{r}
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  )
}
