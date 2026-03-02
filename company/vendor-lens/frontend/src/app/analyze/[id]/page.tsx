'use client'
import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import CompareButton from '@/components/CompareButton'

type Risk = {
  level: 'low' | 'medium' | 'high'
  description: string
}

type Plan = {
  name: string
  price_usd_monthly: number | null
  price_usd_annual: number | null
  is_free_tier: boolean
  key_features: string[]
  limits: Record<string, string>
}

type AnalysisResult = {
  vendor_name: string
  summary: string
  plans: Plan[]
  free_tier: boolean
  open_source: boolean
  self_hostable: boolean
  risks: Risk[]
  alternatives: string[]
  best_for: string
  verdict: string
}

type Analysis = {
  id: string
  url: string
  status: 'pending' | 'processing' | 'done' | 'failed'
  result: AnalysisResult | null
  error: string | null
  created_at: string
}

function VerdictBadge({ verdict }: { verdict: string }) {
  const lower = verdict.toLowerCase()
  let cls = 'bg-gray-100 text-gray-700'
  let label = 'Analyzed'
  if (lower.includes('recommend') || lower.includes('great') || lower.includes('excellent')) {
    cls = 'bg-green-100 text-green-800'
    label = 'Recommended'
  } else if (lower.includes('avoid') || lower.includes('not recommend') || lower.includes('poor')) {
    cls = 'bg-red-100 text-red-800'
    label = 'Avoid'
  } else if (lower.includes('caution') || lower.includes('careful') || lower.includes('consider')) {
    cls = 'bg-yellow-100 text-yellow-800'
    label = 'Use Caution'
  }
  return (
    <span className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium ${cls}`}>
      {label}
    </span>
  )
}

function RiskBadge({ level }: { level: string }) {
  const map: Record<string, string> = {
    low: 'bg-yellow-50 border-yellow-200 text-yellow-800',
    medium: 'bg-orange-50 border-orange-200 text-orange-800',
    high: 'bg-red-50 border-red-200 text-red-800',
  }
  const cls = map[level] ?? 'bg-gray-50 border-gray-200 text-gray-700'
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-semibold border ${cls} capitalize`}>
      {level}
    </span>
  )
}

export default function AnalysisPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const [data, setData] = useState<Analysis | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let timer: NodeJS.Timeout
    async function poll() {
      try {
        const res = await fetch(`/api/analyses/${id}`)
        if (!res.ok) throw new Error('Analysis not found')
        const json: Analysis = await res.json()
        setData(json)
        if (json.status === 'pending' || json.status === 'processing') {
          timer = setTimeout(poll, 2000)
        }
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : 'Failed to load analysis')
      }
    }
    poll()
    return () => clearTimeout(timer)
  }, [id])

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Navbar */}
      <nav className="sticky top-0 z-10 bg-white border-b border-gray-200">
        <div className="max-w-5xl mx-auto px-4 h-14 flex items-center gap-4">
          <button
            onClick={() => router.push('/')}
            className="flex items-center gap-1 text-gray-500 hover:text-gray-900 transition-colors text-sm"
          >
            <span>←</span> <span>Back</span>
          </button>
          <Link href="/" className="font-bold text-gray-900 text-lg">VendorLens</Link>
          <div className="flex-1" />
          <Link
            href="/"
            className="text-sm bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700 transition-colors"
          >
            Analyze another →
          </Link>
        </div>
      </nav>

      {/* Loading */}
      {!data && !error && (
        <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
          <div className="animate-spin rounded-full h-10 w-10 border-4 border-blue-500 border-t-transparent" />
          <p className="text-gray-400 text-sm">Loading analysis…</p>
        </div>
      )}

      {/* Processing */}
      {data && (data.status === 'pending' || data.status === 'processing') && (
        <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
          <div className="animate-spin rounded-full h-10 w-10 border-4 border-blue-500 border-t-transparent" />
          <p className="text-gray-600 font-medium">Analyzing pricing page…</p>
          <p className="text-gray-400 text-sm">{data.url}</p>
          <p className="text-gray-400 text-xs">This usually takes 10–30 seconds</p>
        </div>
      )}

      {/* Error */}
      {(error || data?.status === 'failed') && (
        <div className="max-w-5xl mx-auto px-4 py-12">
          <div className="bg-red-50 border border-red-200 rounded-2xl p-8 text-center">
            <p className="text-red-600 font-medium mb-2">Analysis failed</p>
            <p className="text-red-400 text-sm mb-4">{error || data?.error || 'Unknown error'}</p>
            <Link href="/" className="text-blue-600 hover:underline text-sm">← Try another URL</Link>
          </div>
        </div>
      )}

      {/* Result */}
      {data?.status === 'done' && data.result && (
        <div className="max-w-5xl mx-auto px-4 py-8">
          {/* Hero card */}
          <div className="bg-white rounded-2xl border border-gray-200 p-6 mb-6 shadow-sm">
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div>
                <div className="flex items-center gap-3 mb-1">
                  <h1 className="text-2xl font-bold text-gray-900">{data.result.vendor_name}</h1>
                  <VerdictBadge verdict={data.result.verdict} />
                </div>
                <a
                  href={data.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-500 text-sm hover:underline"
                >
                  {data.url}
                </a>
              </div>
              <CompareButton analysisId={data.id} vendorName={data.result.vendor_name} />
            </div>

            <p className="text-gray-600 mt-4 leading-relaxed">{data.result.summary}</p>

            {/* Verdict highlight */}
            <div className="mt-4 p-4 bg-blue-50 rounded-xl border border-blue-100">
              <p className="text-sm font-medium text-blue-900">💡 Verdict</p>
              <p className="text-sm text-blue-800 mt-1">{data.result.verdict}</p>
            </div>
          </div>

          {/* Quick badges row */}
          <div className="flex flex-wrap gap-2 mb-6">
            {data.result.free_tier && (
              <span className="inline-flex items-center gap-1 px-3 py-1 bg-green-100 text-green-800 text-sm rounded-full font-medium">
                ✓ Free tier available
              </span>
            )}
            {data.result.open_source && (
              <span className="inline-flex items-center gap-1 px-3 py-1 bg-purple-100 text-purple-800 text-sm rounded-full font-medium">
                ✓ Open source
              </span>
            )}
            {data.result.self_hostable && (
              <span className="inline-flex items-center gap-1 px-3 py-1 bg-indigo-100 text-indigo-800 text-sm rounded-full font-medium">
                ✓ Self-hostable
              </span>
            )}
            {data.result.best_for && data.result.best_for !== 'all' && (
              <span className="inline-flex items-center gap-1 px-3 py-1 bg-gray-100 text-gray-700 text-sm rounded-full">
                Best for: {data.result.best_for}
              </span>
            )}
          </div>

          {/* Plans grid */}
          {data.result.plans.length > 0 && (
            <section className="mb-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-3">Pricing Plans</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {data.result.plans.map((plan) => (
                  <div
                    key={plan.name}
                    className={`bg-white rounded-2xl border p-5 shadow-sm flex flex-col ${plan.is_free_tier ? 'border-green-200' : 'border-gray-200'}`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="font-semibold text-gray-900">{plan.name}</h3>
                      {plan.is_free_tier && (
                        <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full font-medium">Free</span>
                      )}
                    </div>

                    {plan.price_usd_monthly !== null ? (
                      <p className="text-2xl font-bold text-blue-600 mb-3">
                        ${plan.price_usd_monthly}
                        <span className="text-sm font-normal text-gray-500">/mo</span>
                      </p>
                    ) : plan.is_free_tier ? (
                      <p className="text-2xl font-bold text-green-600 mb-3">Free</p>
                    ) : (
                      <p className="text-lg font-semibold text-gray-500 mb-3">Contact sales</p>
                    )}

                    {plan.price_usd_annual !== null && plan.price_usd_monthly !== null && (
                      <p className="text-xs text-gray-400 -mt-2 mb-2">
                        ${plan.price_usd_annual}/mo billed annually
                      </p>
                    )}

                    <ul className="text-sm text-gray-600 space-y-1.5 flex-1">
                      {plan.key_features.map((f, i) => (
                        <li key={i} className="flex items-start gap-1.5">
                          <span className="text-green-500 mt-0.5 shrink-0">✓</span>
                          <span>{f}</span>
                        </li>
                      ))}
                    </ul>

                    {Object.keys(plan.limits).length > 0 && (
                      <div className="mt-3 pt-3 border-t border-gray-100">
                        <p className="text-xs font-medium text-gray-500 mb-1">Limits</p>
                        {Object.entries(plan.limits).map(([k, v]) => (
                          <div key={k} className="flex justify-between text-xs text-gray-500">
                            <span>{k}</span>
                            <span className="font-medium text-gray-700">{v}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Risks */}
          {data.result.risks.length > 0 && (
            <section className="mb-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-3">⚠️ Risk Flags</h2>
              <div className="bg-white rounded-2xl border border-gray-200 divide-y divide-gray-100 shadow-sm overflow-hidden">
                {data.result.risks.map((r, i) => (
                  <div key={i} className="flex items-start gap-3 p-4">
                    <div className="pt-0.5">
                      <RiskBadge level={r.level} />
                    </div>
                    <p className="text-sm text-gray-700 leading-relaxed">{r.description}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Alternatives */}
          {data.result.alternatives.length > 0 && (
            <section className="mb-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-3">Alternatives to consider</h2>
              <div className="flex flex-wrap gap-2">
                {data.result.alternatives.map((alt) => (
                  <span
                    key={alt}
                    className="px-3 py-1.5 bg-white border border-gray-200 rounded-full text-sm text-gray-700 shadow-sm hover:border-blue-300 transition-colors cursor-default"
                  >
                    {alt}
                  </span>
                ))}
              </div>
            </section>
          )}

          {/* Footer CTA */}
          <div className="text-center pt-6 pb-2">
            <p className="text-gray-400 text-xs mb-2">
              Analyzed by VendorLens · {new Date(data.created_at).toLocaleDateString()}
            </p>
            <Link href="/" className="text-blue-500 hover:underline text-sm">← Analyze another vendor</Link>
          </div>
        </div>
      )}
    </div>
  )
}
