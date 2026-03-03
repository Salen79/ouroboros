'use client'
import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { getAnalysis } from '@/lib/api'
import CompareButton from '@/components/CompareButton'

type Risk = {
  level: 'low' | 'medium' | 'high'
  description: string
}

type Plan = {
  name: string
  price?: string | number | null
  features?: string[]
  [key: string]: unknown
}

type AnalysisResult = {
  plans?: Plan[]
  summary?: string
  verdict?: string
  risk_flags?: string[]
  vendor_name?: string
}

type Analysis = {
  id: string
  status: 'pending' | 'completed' | 'failed'
  url: string
  result?: AnalysisResult
}

function vendorLabel(analysis: Analysis): string {
  const name = analysis.result?.vendor_name
  if (name) return name
  try {
    return new URL(analysis.url).hostname.replace(/^www\./, '')
  } catch {
    return analysis.url
  }
}

function formatPrice(price: string | number | null | undefined): string {
  if (price == null) return '---'
  if (typeof price === 'number') return `$${price}`
  return String(price)
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
  const [data, setData] = useState<Analysis | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      try {
        const json = await getAnalysis(id) as Analysis
        setData(json)
        if (json.status === 'pending') {
          timer = setTimeout(poll, 2000)
        }
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : 'Failed to load analysis')
      }
    }
    poll()
    return () => clearTimeout(timer)
  }, [id])

  if (error) return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-4 p-8">
      <p className="text-red-500 text-lg">{error}</p>
      <Link href="/" className="text-blue-500 hover:underline text-sm">← Back to home</Link>
    </div>
  )

  if (!data) return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-4">
      <div className="animate-spin rounded-full h-12 w-12 border-4 border-blue-500 border-t-transparent" />
      <p className="text-gray-400">Loading…</p>
    </div>
  )

  if (data.status === 'pending') {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-blue-500 border-t-transparent" />
        <p className="text-gray-500">Analyzing pricing page…</p>
        <p className="text-gray-400 text-sm">{data.url}</p>
      </div>
    )
  }

  if (data.status === 'failed') {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4 p-8">
        <p className="text-red-500 text-lg">Analysis failed. Please try another URL.</p>
        <Link href="/" className="text-blue-500 hover:underline text-sm">← Back to home</Link>
      </div>
    )
  }

  const result = data.result ?? {}
  const plans = result.plans ?? []
  const riskFlags = result.risk_flags ?? []
  const label = vendorLabel(data)

  return (
    <main className="max-w-4xl mx-auto px-6 py-12">
      {/* Header */}
      <div className="flex items-start justify-between mb-8">
        <div>
          <Link href="/" className="text-gray-400 text-sm hover:text-gray-600 mb-2 block">← Back</Link>
          <h1 className="text-3xl font-bold text-gray-900">{label}</h1>
          <a href={data.url} target="_blank" rel="noopener noreferrer" className="text-blue-500 text-sm hover:underline break-all">{data.url}</a>
        </div>
        <CompareButton analysisId={data.id} vendorName={label} />
      </div>

      {/* Summary */}
      {result.summary && (
        <p className="text-gray-600 mb-8 text-lg leading-relaxed">{result.summary}</p>
      )}

      {/* Verdict */}
      {result.verdict && (
        <section className="mb-8 bg-blue-50 border border-blue-100 rounded-2xl p-5">
          <h2 className="text-sm font-semibold text-blue-700 uppercase tracking-wide mb-2">Verdict</h2>
          <p className="text-gray-800">{result.verdict}</p>
        </section>
      )}

      {/* Plans table */}
      {plans.length > 0 && (
        <section className="mb-8">
          <h2 className="text-xl font-semibold mb-4">Pricing Plans</h2>
          <div className="overflow-x-auto rounded-2xl border border-gray-200 shadow-sm">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="text-left px-4 py-3 font-semibold text-gray-700">Plan</th>
                  <th className="text-left px-4 py-3 font-semibold text-gray-700">Price</th>
                  <th className="text-left px-4 py-3 font-semibold text-gray-700">Features</th>
                </tr>
              </thead>
              <tbody>
                {plans.map((plan, i) => (
                  <tr key={plan.name ?? i} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                    <td className="px-4 py-3 font-medium text-gray-900 whitespace-nowrap">{plan.name}</td>
                    <td className="px-4 py-3 text-blue-700 font-semibold whitespace-nowrap">{formatPrice(plan.price)}</td>
                    <td className="px-4 py-3 text-gray-600">
                      {Array.isArray(plan.features) && plan.features.length > 0
                        ? plan.features.join(' · ')
                        : '---'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Risk flags */}
      {riskFlags.length > 0 && (
        <section className="mb-8">
          <h2 className="text-xl font-semibold mb-4">Risk Flags</h2>
          <ul className="space-y-2">
            {riskFlags.map((r, i) => (
              <li key={i} className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-xl p-3 text-sm text-amber-900">
                <span className="mt-0.5">⚠</span><span>{r}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Compare CTA */}
      <div className="mt-10 pt-8 border-t border-gray-100 text-center">
        <p className="text-gray-500 text-sm mb-3">Want to compare this vendor against others?</p>
        <Link href="/compare" className="inline-block px-5 py-2.5 bg-gray-900 hover:bg-gray-700 text-white text-sm font-semibold rounded-xl transition-colors">
          Go to Compare →
        </Link>
      </div>
    </main>
  )
}
