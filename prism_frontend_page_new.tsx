'use client'

import { useState } from 'react'
import {
  Chart as ChartJS,
  RadialLinearScale,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
  Legend,
} from 'chart.js'
import { Radar } from 'react-chartjs-2'

ChartJS.register(RadialLinearScale, PointElement, LineElement, Filler, Tooltip, Legend)

interface PerspectiveScores {
  political_lean: number
  political_lean_confidence: number
  institutional_trust: number
  institutional_trust_confidence: number
  moral_foundation: number
  moral_foundation_confidence: number
  epistemic_style: number
  epistemic_style_confidence: number
  solution_orientation: number
  solution_orientation_confidence: number
  scope_of_concern: number
  scope_of_concern_confidence: number
}

interface AnalysisResult {
  url_hash: string
  title: string
  perspective_scores: PerspectiveScores
  created_at: string
}

function scoreToLabel(dimension: keyof PerspectiveScores, score: number): string {
  switch (dimension) {
    case 'political_lean':
      if (score <= -0.6) return 'Far Left'
      if (score <= -0.2) return 'Leans Left'
      if (score < 0.2) return 'Center'
      if (score < 0.6) return 'Leans Right'
      return 'Far Right'
    case 'institutional_trust':
      if (score <= -0.6) return 'Very Skeptical'
      if (score <= -0.2) return 'Skeptical'
      if (score < 0.2) return 'Neutral'
      if (score < 0.6) return 'Trusting'
      return 'Very Trusting'
    case 'moral_foundation':
      if (score <= -0.6) return 'Strong Care/Harm Focus'
      if (score <= -0.2) return 'Care/Harm Focus'
      if (score < 0.2) return 'Balanced'
      if (score < 0.6) return 'Authority/Loyalty Focus'
      return 'Strong Authority/Loyalty Focus'
    case 'epistemic_style':
      if (score <= -0.6) return 'Strongly Narrative/Emotional'
      if (score <= -0.2) return 'Narrative/Emotional'
      if (score < 0.2) return 'Balanced'
      if (score < 0.6) return 'Data/Analytical'
      return 'Strongly Data/Analytical'
    case 'solution_orientation':
      if (score <= -0.6) return 'Systemic Change'
      if (score <= -0.2) return 'Leans Systemic'
      if (score < 0.2) return 'Mixed'
      if (score < 0.6) return 'Leans Individual'
      return 'Individual Responsibility'
    case 'scope_of_concern':
      if (score <= -0.6) return 'Local/Community'
      if (score <= -0.2) return 'Regional'
      if (score < 0.2) return 'National'
      if (score < 0.6) return 'International'
      return 'Global'
    default:
      return ''
  }
}

const DIMENSION_META: Array<{
  key: keyof PerspectiveScores
  label: string
  leftLabel: string
  rightLabel: string
  description: string
}> = [
  { key: 'political_lean', label: 'Political Lean', leftLabel: 'Left', rightLabel: 'Right', description: 'Where the article sits on the political spectrum' },
  { key: 'institutional_trust', label: 'Institutional Trust', leftLabel: 'Skeptical', rightLabel: 'Trusting', description: 'How the article treats official institutions, experts, governments' },
  { key: 'moral_foundation', label: 'Moral Foundation', leftLabel: 'Care/Harm', rightLabel: 'Authority', description: 'Whether it appeals to care for people or to order and authority' },
  { key: 'epistemic_style', label: 'Epistemic Style', leftLabel: 'Emotional', rightLabel: 'Analytical', description: 'Does it persuade through emotion/narrative or data/logic?' },
  { key: 'solution_orientation', label: 'Solutions', leftLabel: 'Systemic', rightLabel: 'Individual', description: 'Does it blame systems and structures, or individual choices?' },
  { key: 'scope_of_concern', label: 'Scope', leftLabel: 'Local', rightLabel: 'Global', description: 'Is the focus local/national or international/global?' },
]

function isNeutralContent(scores: PerspectiveScores): boolean {
  const dimensionKeys: (keyof PerspectiveScores)[] = [
    'political_lean', 'institutional_trust', 'moral_foundation',
    'epistemic_style', 'solution_orientation', 'scope_of_concern',
  ]
  const neutralCount = dimensionKeys.filter(
    (k) => Math.abs(scores[k] as number) < 0.25
  ).length
  return neutralCount >= 4
}

function ScoreBar({ score }: { score: number }) {
  const clampedScore = Math.max(-1, Math.min(1, score))
  const isPositive = clampedScore >= 0
  const pct = Math.abs(clampedScore) * 50

  return (
    <div className="relative h-3 w-full bg-gray-800 rounded-full overflow-hidden">
      <div className="absolute inset-0 flex">
        <div className="w-1/2 flex justify-end">
          {!isPositive && (
            <div
              className="h-full bg-purple-500 rounded-l-full"
              style={{ width: `${pct}%` }}
            />
          )}
        </div>
        <div className="w-px bg-gray-600" />
        <div className="w-1/2">
          {isPositive && (
            <div
              className="h-full bg-blue-500 rounded-r-full"
              style={{ width: `${pct}%` }}
            />
          )}
        </div>
      </div>
    </div>
  )
}

function DimensionRow({
  dimMeta,
  scores,
}: {
  dimMeta: (typeof DIMENSION_META)[number]
  scores: PerspectiveScores
}) {
  const score = scores[dimMeta.key] as number
  const confidence = scores[`${dimMeta.key}_confidence` as keyof PerspectiveScores] as number
  const label = scoreToLabel(dimMeta.key, score)

  return (
    <div className="bg-gray-900 rounded-lg p-4">
      <div className="flex items-center justify-between mb-1">
        <div>
          <span className="text-sm font-medium text-gray-300">{dimMeta.label}</span>
          <p className="text-xs text-gray-600 mt-0.5">{dimMeta.description}</p>
        </div>
        <div className="flex items-center gap-2 ml-4 shrink-0">
          <span className="text-sm font-semibold text-white">{label}</span>
          <span className="text-xs text-gray-500">
            {Math.round(confidence * 100)}% conf.
          </span>
        </div>
      </div>
      <div className="flex items-center gap-2 mt-2">
        <span className="text-xs text-gray-500 w-14 text-right">{dimMeta.leftLabel}</span>
        <div className="flex-1">
          <ScoreBar score={score} />
        </div>
        <span className="text-xs text-gray-500 w-14">{dimMeta.rightLabel}</span>
      </div>
    </div>
  )
}

function RadarChart({ scores }: { scores: PerspectiveScores }) {
  const toRadarValue = (v: number) => ((v + 1) / 2) * 10

  const data = {
    labels: ['Political', 'Inst. Trust', 'Moral Found.', 'Epistemic', 'Solutions', 'Scope'],
    datasets: [
      {
        label: 'Perspective',
        data: [
          toRadarValue(scores.political_lean),
          toRadarValue(scores.institutional_trust),
          toRadarValue(scores.moral_foundation),
          toRadarValue(scores.epistemic_style),
          toRadarValue(scores.solution_orientation),
          toRadarValue(scores.scope_of_concern),
        ],
        backgroundColor: 'rgba(147, 51, 234, 0.2)',
        borderColor: 'rgba(147, 51, 234, 0.8)',
        borderWidth: 2,
        pointBackgroundColor: 'rgba(147, 51, 234, 1)',
        pointBorderColor: '#fff',
        pointHoverBackgroundColor: '#fff',
        pointHoverBorderColor: 'rgba(147, 51, 234, 1)',
      },
    ],
  }

  const options = {
    responsive: true,
    maintainAspectRatio: true,
    scales: {
      r: {
        min: 0,
        max: 10,
        ticks: {
          stepSize: 2,
          color: 'rgba(156, 163, 175, 0.6)',
          backdropColor: 'transparent',
          font: { size: 10 },
        },
        grid: { color: 'rgba(75, 85, 99, 0.4)' },
        angleLines: { color: 'rgba(75, 85, 99, 0.4)' },
        pointLabels: {
          color: 'rgba(209, 213, 219, 0.9)',
          font: { size: 12 },
        },
      },
    },
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          label: (ctx: { parsed: { r: number } }) => {
            const raw = ctx.parsed.r
            const original = (raw / 10) * 2 - 1
            return `Score: ${original.toFixed(2)}`
          },
        },
      },
    },
  }

  return (
    <div className="bg-gray-900 rounded-xl p-6 flex justify-center">
      <div className="w-full max-w-sm">
        <Radar data={data} options={options} />
      </div>
    </div>
  )
}

function HowToRead({ expanded, onToggle }: { expanded: boolean; onToggle: () => void }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-gray-800 transition-colors"
      >
        <span className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          📖 How to read this
        </span>
        <span className="text-gray-500 text-lg">{expanded ? '▲' : '▼'}</span>
      </button>
      {expanded && (
        <div className="px-5 pb-5 space-y-3 text-sm text-gray-400 border-t border-gray-800 pt-4">
          <p>
            <span className="text-gray-200 font-medium">The radar chart</span> shows a fingerprint of the article&apos;s perspective across 6 dimensions. The center of the chart (5 on each axis) means neutral. Points pushed outward mean a stronger position.
          </p>
          <p>
            <span className="text-gray-200 font-medium">The bars</span> show direction: left half = left/skeptical/emotional/systemic/local. Right half = right/trusting/analytical/individual/global. A bar at center means the article doesn&apos;t take a strong position on that dimension — that&apos;s completely normal.
          </p>
          <p>
            <span className="text-gray-200 font-medium">Confidence %</span> tells you how clearly the model detected that signal. 30% confidence means the article had mixed signals. 90% means it was unambiguous.
          </p>
          <p className="text-gray-500 text-xs">
            Prism is not a fact-checker. It analyzes framing and perspective — the &quot;how&quot; of storytelling, not the &quot;what&quot;.
          </p>
        </div>
      )}
    </div>
  )
}

export default function Home() {
  const [url, setUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [howToReadOpen, setHowToReadOpen] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!url.trim()) return

    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url.trim() }),
      })
      const data = await res.json()
      if (!res.ok) {
        setError(data.detail ?? `Error ${res.status}`)
      } else {
        setResult(data as AnalysisResult)
      }
    } catch {
      setError('Network error — could not reach the server.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="min-h-screen flex flex-col items-center px-4 py-16">
      <div className="w-full max-w-2xl">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-6xl font-extrabold tracking-tight mb-3 bg-gradient-to-r from-purple-400 to-blue-400 bg-clip-text text-transparent">
            Prism
          </h1>
          <p className="text-xl text-gray-300 mb-3">Reveal the perspective behind any article</p>
          <p className="text-sm text-gray-500 max-w-lg mx-auto leading-relaxed">
            Paste a news article or opinion piece and Prism will reveal the hidden perspective dimensions shaping how the story is told — political lean, who it trusts, how it frames solutions, and more.
          </p>
        </div>

        {/* What works best */}
        <div className="flex flex-wrap gap-2 justify-center mb-8">
          {['✅ News articles', '✅ Opinion pieces', '✅ Blog posts', '⚠️ Not for: product docs, changelogs'].map((tag) => (
            <span
              key={tag}
              className={`text-xs px-3 py-1.5 rounded-full ${
                tag.startsWith('⚠️')
                  ? 'bg-yellow-950 text-yellow-400 border border-yellow-800'
                  : 'bg-gray-800 text-gray-400 border border-gray-700'
              }`}
            >
              {tag}
            </span>
          ))}
        </div>

        {/* Input form */}
        <form onSubmit={handleSubmit} className="flex gap-3 mb-8">
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="Paste a news article URL…"
            required
            className="flex-1 bg-gray-900 border border-gray-700 rounded-xl px-5 py-4 text-gray-100 placeholder-gray-500 focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500 text-base transition-colors"
          />
          <button
            type="submit"
            disabled={loading}
            className="bg-purple-600 hover:bg-purple-500 disabled:bg-purple-800 disabled:cursor-not-allowed text-white font-semibold px-7 py-4 rounded-xl transition-colors text-base whitespace-nowrap"
          >
            {loading ? 'Analyzing…' : 'Analyze'}
          </button>
        </form>

        {/* Loading */}
        {loading && (
          <div className="flex items-center justify-center gap-3 py-12 text-gray-400">
            <svg
              className="animate-spin h-6 w-6 text-purple-500"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
            <span>Analyzing article perspective…</span>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="bg-red-950 border border-red-700 text-red-300 rounded-xl px-5 py-4 text-sm">
            {error}
          </div>
        )}

        {/* Results */}
        {result && (
          <div className="space-y-6">
            {/* Title */}
            <div className="bg-gray-900 rounded-xl px-6 py-5 border border-gray-800">
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Article</p>
              <h2 className="text-lg font-semibold text-gray-100 leading-snug">{result.title}</h2>
            </div>

            {/* Neutral content warning */}
            {isNeutralContent(result.perspective_scores) && (
              <div className="bg-yellow-950 border border-yellow-800 text-yellow-300 rounded-xl px-5 py-4 text-sm flex gap-3">
                <span className="text-lg">⚠️</span>
                <div>
                  <p className="font-medium mb-1">This content appears to be neutral or technical</p>
                  <p className="text-yellow-400 text-xs">Prism works best with news articles, opinion pieces, and commentary. Product docs, changelogs, and scientific papers typically score near zero on most dimensions — that&apos;s expected, not a bug.</p>
                </div>
              </div>
            )}

            {/* Radar chart */}
            <RadarChart scores={result.perspective_scores} />

            {/* How to read */}
            <HowToRead expanded={howToReadOpen} onToggle={() => setHowToReadOpen(!howToReadOpen)} />

            {/* Dimension breakdown */}
            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider px-1">
                Dimension Breakdown
              </h3>
              {DIMENSION_META.map((dim) => (
                <DimensionRow key={dim.key} dimMeta={dim} scores={result.perspective_scores} />
              ))}
            </div>
          </div>
        )}
      </div>
    </main>
  )
}
