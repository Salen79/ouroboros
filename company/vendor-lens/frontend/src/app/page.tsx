import { listAnalyses } from '@/lib/api'
import AnalyzeForm from '@/components/AnalyzeForm'
import Link from 'next/link'

// ─── Helpers ────────────────────────────────────────────────────────────────

function getHostname(url: string) {
  try { return new URL(url).hostname.replace('www.', '') } catch { return url }
}

function getVerdictBadge(verdict: string): { label: string; className: string } {
  const v = (verdict ?? '').toLowerCase()
  if (v.includes('recommend') || v.includes('great') || v.includes('excellent') || v.includes('good'))
    return { label: '✓ Recommended', className: 'bg-emerald-50 text-emerald-700 border-emerald-200' }
  if (v.includes('caution') || v.includes('consider') || v.includes('complex') || v.includes('mixed'))
    return { label: '⚡ Caution', className: 'bg-amber-50 text-amber-700 border-amber-200' }
  if (v.includes('avoid') || v.includes('expensive') || v.includes('risky'))
    return { label: '✕ Avoid', className: 'bg-red-50 text-red-700 border-red-200' }
  return { label: '• Analyzed', className: 'bg-blue-50 text-blue-700 border-blue-200' }
}

// ─── Analysis List Row ───────────────────────────────────────────────────────

function AnalysisRow({ item }: { item: any }) {
  const r = item.result
  const hostname = getHostname(item.url)
  const vendorName = r?.vendor_name ?? hostname
  const planCount = r?.plans?.length ?? 0
  const hasFree = r?.plans?.some((p: any) => p.price_usd_monthly === 0 || p.price_usd_monthly === null || p.price_usd_monthly === undefined)
  const risks = r?.risks?.length ?? 0
  const verdict = getVerdictBadge(r?.verdict ?? '')
  const lowestPaid = r?.plans
    ?.filter((p: any) => typeof p.price_usd_monthly === 'number' && p.price_usd_monthly > 0)
    ?.sort((a: any, b: any) => a.price_usd_monthly - b.price_usd_monthly)[0]

  // Get initials / first char for avatar
  const initials = vendorName
    .split(/[ \-_]/)
    .map((w: string) => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)

  // Color based on name for variety
  const colors = [
    'from-blue-500 to-indigo-600',
    'from-violet-500 to-purple-600',
    'from-emerald-500 to-teal-600',
    'from-orange-500 to-red-500',
    'from-pink-500 to-rose-600',
    'from-cyan-500 to-blue-500',
    'from-amber-500 to-orange-500',
  ]
  const colorIdx = vendorName.charCodeAt(0) % colors.length

  return (
    <Link
      href={`/analyze/${item.id}`}
      className="group flex items-center gap-3 px-4 py-3 hover:bg-blue-50/40 transition-colors border-b border-gray-100 last:border-0"
    >
      {/* Avatar */}
      <div className={`flex-shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br ${colors[colorIdx]} flex items-center justify-center text-white text-xs font-bold shadow-sm`}>
        {initials}
      </div>

      {/* Name + domain */}
      <div className="flex-1 min-w-0">
        <div className="text-sm font-semibold text-gray-900 group-hover:text-blue-700 transition-colors truncate">
          {vendorName}
        </div>
        <div className="text-xs text-gray-400 truncate hidden sm:block">{hostname}</div>
      </div>

      {/* Plans — hidden on mobile */}
      <div className="hidden sm:flex flex-col items-center w-14">
        <span className="text-sm font-medium text-gray-700">{planCount}</span>
        <span className="text-xs text-gray-400">plans</span>
      </div>

      {/* Starting price */}
      <div className="hidden md:flex flex-col items-center w-20 text-center">
        {lowestPaid ? (
          <span className="text-sm font-medium text-gray-700">${lowestPaid.price_usd_monthly}/mo</span>
        ) : hasFree ? (
          <span className="text-sm font-medium text-emerald-600">Free</span>
        ) : (
          <span className="text-xs text-gray-400">—</span>
        )}
      </div>

      {/* Risks */}
      <div className="hidden sm:flex flex-col items-center w-12 text-center">
        {risks > 0 ? (
          <span className="text-sm font-medium text-amber-600">{risks} ⚠</span>
        ) : (
          <span className="text-sm font-medium text-emerald-600">✓</span>
        )}
      </div>

      {/* Verdict */}
      <div className="flex-shrink-0">
        <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${verdict.className}`}>
          {verdict.label}
        </span>
      </div>

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
  const done = analyses.filter((a) => a.status === 'done' && a.result).slice(0, 12)

  const suggestions = ['stripe.com/pricing', 'vercel.com/pricing', 'supabase.com/pricing']

  return (
    <main className="min-h-screen bg-white">

      {/* Minimal nav */}
      <nav className="flex items-center justify-between px-6 py-4">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center">
            <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          </div>
          <span className="font-bold text-gray-900 tracking-tight">VendorLens</span>
        </div>
        <span className="text-xs text-gray-400 hidden sm:block">SaaS Pricing Intelligence</span>
      </nav>

      {/* Hero — Google-style centered search */}
      <section className="flex flex-col items-center justify-center px-4 pt-12 pb-16 sm:pt-20 sm:pb-24">
        {/* Icon + headline */}
        <div className="flex flex-col items-center mb-10">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-lg mb-6">
            <svg className="w-7 h-7 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          </div>
          <h1 className="text-5xl sm:text-6xl font-black text-gray-950 tracking-tight">VendorLens</h1>
          <p className="mt-3 text-base sm:text-lg text-gray-500 text-center max-w-sm leading-relaxed">
            Paste a pricing URL. Get instant clarity on plans,&nbsp;costs&nbsp;&amp;&nbsp;risks.
          </p>
        </div>

        {/* The main search box */}
        <div className="w-full max-w-xl">
          <AnalyzeForm />
        </div>

        {/* Suggestion pills */}
        <div className="mt-4 flex flex-wrap items-center justify-center gap-x-3 gap-y-1">
          <span className="text-sm text-gray-400">Try:</span>
          {suggestions.map((s) => (
            <a
              key={s}
              href={`/?q=${encodeURIComponent(s)}`}
              className="text-sm text-blue-600 hover:text-blue-800 hover:underline font-mono"
            >
              {s}
            </a>
          ))}
        </div>
      </section>

      {/* Recently analyzed — secondary section */}
      {done.length > 0 && (
        <section className="max-w-2xl mx-auto px-4 pb-20">
          <div className="border-t border-gray-100 pt-8">

            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">Community analyses</h2>
              <span className="text-xs text-gray-400 tabular-nums">{done.length} vendors</span>
            </div>

            <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden shadow-sm">
              {/* Column headers — desktop only */}
              <div className="hidden sm:grid grid-cols-[32px_1fr_56px_80px_48px_96px_16px] gap-3 px-4 py-2 bg-gray-50/80 border-b border-gray-100">
                <div />
                <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Vendor</div>
                <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide text-center">Plans</div>
                <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide text-center hidden md:block">From</div>
                <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide text-center">Risks</div>
                <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide text-center">Verdict</div>
                <div />
              </div>

              {done.map((item) => (
                <AnalysisRow key={item.id} item={item} />
              ))}
            </div>

            <p className="mt-4 text-xs text-center text-gray-400">
              Powered by Gemini 2.0 Flash &middot; Data may be outdated
            </p>
          </div>
        </section>
      )}

      {/* Footer */}
      <footer className="text-center py-8 text-xs text-gray-400 border-t border-gray-100">
        <span>VendorLens &mdash; Instant clarity on SaaS pricing</span>
      </footer>

    </main>
  )
}
