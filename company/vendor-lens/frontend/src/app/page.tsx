import Link from 'next/link'
import AnalyzeForm from '@/components/AnalyzeForm'

export default function HomePage() {
  return (
    <main className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50">
      {/* Hero */}
      <section className="px-6 py-24 text-center max-w-4xl mx-auto">
        <h1 className="text-5xl font-bold text-gray-900 mb-4">
          Instant SaaS Pricing Intelligence
        </h1>
        <p className="text-xl text-gray-600 mb-8 max-w-2xl mx-auto">
          Paste a vendor URL → get structured pricing breakdown, cost projections,
          risk flags, and side-by-side comparisons. Stop guessing. Start deciding.
        </p>
        <AnalyzeForm />
      </section>

      {/* Value props */}
      <section className="px-6 pb-20 max-w-5xl mx-auto">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {[
            { icon: '🔍', title: 'Parse Any Pricing Page', desc: 'Works with Stripe, Vercel, AWS, Linear, Notion — any URL.' },
            { icon: '📊', title: 'Cost Projections', desc: 'See exactly what you\'ll pay at 100, 1k, 10k users.' },
            { icon: '⚠️', title: 'Risk Flags', desc: 'Vendor lock-in, hidden overages, missing SLAs — surfaced automatically.' },
          ].map((card) => (
            <div key={card.title} className="bg-white rounded-2xl p-6 shadow-sm border border-gray-100">
              <div className="text-3xl mb-3">{card.icon}</div>
              <h3 className="font-semibold text-gray-900 mb-2">{card.title}</h3>
              <p className="text-gray-500 text-sm">{card.desc}</p>
            </div>
          ))}
        </div>
      </section>
    </main>
  )
}
