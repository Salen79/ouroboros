import { listAnalyses } from '@/lib/api'
import AnalyzeForm from '@/components/AnalyzeForm'
import Link from 'next/link'

// ─── Helpers ────────────────────────────────────────────────────────────────

function getHostname(url: string) {
  try { return new URL(url).hostname.replace('www.', '') } catch { return url }
}

function getVerdictBadge(verdict: string): { label: string; className: string } {
  const v = (verdict ?? '').toLowerCase()
  if (v.includes('recommend') || v.includes('great') || v.includes('excellent'))
    return { label: '✓ Recommended', className: 'bg-emerald-50 text-emerald-700 border-emerald-200' }
  if (v.includes('caution') || v.includes('consider') || v.includes('complex'))
    return { label: '⚡ Use Caution', className: 'bg-amber-50 text-amber-700 border-amber-200' }
  if (v.includes('avoid') || v.includes('expensive') || v.includes('risky'))
    return { label: '✕ Avoid', className: 'bg-red-50 text-red-700 border-red-200' }
  return { label: '• Analyzed', className: 'bg-blue-50 text-blue-700 border-blue-200' }
}

// ─── Community Analyses Table Row ────────────────────────────────────────────

function AnalysisRow({ item }: { item: any }) {
  const r = item.result
  const hostname = getHostname(item.url)
  const vendorName = r?.vendor_name ?? hostname
  const planCount = r?.plans?.length ?? 0
  const hasFree = r?.plans?.some((p: any) => p.price_usd_monthly === 0 || p.price_usd_monthly === null)
  const risks = r?.risks?.length ?? 0
  const verdict = getVerdictBadge(r?.verdict ?? '')
  const lowestPaid = r?.plans
    ?.filter((p: any) => p.price_usd_monthly > 0)
    ?.sort((a: any, b: any) => a.price_usd_monthly - b.price_usd_monthly)[0]

  return (
    <Link
      href={`/analyze/${item.id}`}
      className="group flex items-center gap-4 px-5 py-4 hover:bg-gray-50 transition-colors border-b border-gray-100 last:border-0"
    >
      {/* Vendor avatar */}
      <div className="flex-shrink-0 w-9 h-9 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center text-white text-sm font-bold shadow-sm">
        {vendorName.charAt(0).toUpperCase()}
      </div>

      {/* Name + hostname */}
      <div className="flex-1 min-w-0">
        <div className="font-semibold text-gray-900 group-hover:text-blue-600 transition-colors truncate">
          {vendorName}
        </div>
        <div className="text-xs text-gray-400 truncate">{hostname}</div>
      </div>

      {/* Plans */}
      <div className="hidden sm:flex flex-col items-center w-16">
        <span className="text-sm font-medium text-gray-700">{planCount}</span>
        <span className="text-xs text-gray-400">plans</span>
      </div>

      {/* Starting price */}
      <div className="hidden md:flex flex-col items-center w-24">
        {lowestPaid ? (
          <>
            <span className="text-sm font-medium text-gray-700">${lowestPaid.price_usd_monthly}/mo</span>
            <span className="text-xs text-gray-400">from</span>
          </>
        ) : hasFree ? (
          <>
            <span className="text-sm font-medium text-emerald-600">Free</span>
            <span className="text-xs text-gray-400">tier</span>
          </>
        ) : (
          <span className="text-xs text-gray-400">—</span>
        )}
      </div>

      {/* Risks */}
      <div className="hidden sm:flex flex-col items-center w-16">
        {risks > 0 ? (
          <>
            <span className="text-sm font-medium text-amber-600">{risks}</span>
            <span className="text-xs text-gray-400">risks</span>
          </>
        ) : (
          <>
            <span className="text-sm font-medium text-emerald-600">0</span>
            <span className="text-xs text-gray-400">risks</span>
          </>
        )}
      </div>

      {/* Verdict badge */}
      <div className="flex-shrink-0">
        <span className={`inline-block text-xs font-medium px-2.5 py-1 rounded-full border ${verdict.className}`}>
          {verdict.label}
        </span>
      </div>

      {/* Arrow */}
      <svg className="flex-shrink-0 w-4 h-4 text-gray-300 group-hover:text-blue-400 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
      </svg>
    </Link>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default async function Home() {
  let analyses: any[] = []
  try { analyses = await listAnalyses(20) } catch {}
  const done = analyses.filter((a) => a.status === 'done' && a.result)

  return (
    <main className="min-h-screen bg-gray-50">

      {/* Hero */}
      <section className="bg-white border-b border-gray-100">
        <div className="max-w-2xl mx-auto px-4 py-16 sm:py-20 text-center">

          <div className="inline-flex items-center gap-1.5 bg-blue-50 text-blue-600 text-xs font-semibold px-3 py-1.5 rounded-full mb-6 tracking-wide uppercase">
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" /></svg>
            SaaS Pricing Intelligence
          </div>

          <h1 className="text-4xl sm:text-5xl font-extrabold text-gray-900 mb-4 tracking-tight leading-tight">
            Decode any SaaS pricing<br />
            <span className="text-blue-600">before you pay</span>
          </h1>

          <p className="text-lg text-gray-500 mb-10 max-w-lg mx-auto leading-relaxed">
            Paste a vendor URL. Get a plain-English breakdown of plans, limits, and hidden risks — in seconds.
          </p>

          <AnalyzeForm />

          <p className="mt-4 text-sm text-gray-400">
            Try:&nbsp;
            <span className="font-mono">stripe.com/pricing</span>&nbsp;·&nbsp;
            <span className="font-mono">vercel.com/pricing</span>&nbsp;·&nbsp;
            <span className="font-mono">supabase.com/pricing</span>
          </p>
        </div>
      </section>

      {/* How it works */}
      <section className="bg-white border-b border-gray-100">
        <div className="max-w-3xl mx-auto px-4 py-8">
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4 sm:gap-0">
            {[
              { step: '1', icon: '🔗', title: 'Paste a URL', desc: 'Any SaaS pricing page' },
              { step: '2', icon: '🤖', title: 'AI Analyzes', desc: 'Plans, limits & risks' },
              { step: '3', icon: '✅', title: 'Get Clarity', desc: 'Plain-English verdict' },
            ].map((s, i) => (
              <div key={s.step} className="flex items-center gap-0">
                <div className="flex flex-col items-center text-center px-6">
                  <div className="text-2xl mb-1">{s.icon}</div>
                  <div className="text-sm font-semibold text-gray-800">{s.title}</div>
                  <div className="text-xs text-gray-400 mt-0.5">{s.desc}</div>
                </div>
                {i < 2 && (
                  <div className="hidden sm:block text-gray-200 text-2xl font-light select-none">→</div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Community Analyses */}
      <section className="max-w-3xl mx-auto px-4 py-10">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-base font-semibold text-gray-800">Community Analyses</h2>
            <p className="text-sm text-gray-400 mt-0.5">Recently analyzed vendors — click any to see full breakdown</p>
          </div>
          {done.length > 0 && (
            <span className="text-xs font-medium text-gray-400 bg-gray-100 px-2.5 py-1 rounded-full">
              {done.length} vendors
            </span>
          )}
        </div>

        {done.length > 0 ? (
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            {/* Table header */}
            <div className="hidden sm:flex items-center gap-4 px-5 py-2.5 bg-gray-50 border-b border-gray-100 text-xs font-medium text-gray-400 uppercase tracking-wide">
              <div className="w-9 flex-shrink-0" />
              <div className="flex-1">Vendor</div>
              <div className="hidden sm:block w-16 text-center">Plans</div>
              <div className="hidden md:block w-24 text-center">Starting at</div>
              <div className="hidden sm:block w-16 text-center">Risks</div>
              <div className="w-28 text-center">Verdict</div>
              <div className="w-4" />
            </div>

            {done.map((item) => (
              <AnalysisRow key={item.id} item={item} />
            ))}
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm px-8 py-12 text-center">
            <div className="text-4xl mb-3">🔍</div>
            <h3 className="text-base font-semibold text-gray-700 mb-1">No analyses yet</h3>
            <p className="text-sm text-gray-400">Be the first — paste a pricing URL above to get started.</p>
          </div>
        )}
      </section>

    </main>
  )
}
