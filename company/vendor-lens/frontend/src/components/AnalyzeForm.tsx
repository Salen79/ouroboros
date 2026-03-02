'use client'
import { useState, useEffect, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { submitAnalysis, getAnalysis } from '@/lib/api'

type Phase = 'idle' | 'submitting' | 'polling' | 'error'

function AnalyzeFormInner() {
  const [url, setUrl] = useState('')
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState('')
  const [statusText, setStatusText] = useState('')
  const router = useRouter()
  const searchParams = useSearchParams()

  useEffect(() => {
    const q = searchParams.get('q')
    if (q) setUrl(q)
  }, [searchParams])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = url.trim()
    if (!trimmed) return

    const normalised = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`

    setPhase('submitting')
    setError('')
    setStatusText('Submitting...')

    try {
      const { id } = await submitAnalysis(normalised)
      setPhase('polling')
      setStatusText('Scraping pricing page...')

      let attempts = 0
      const maxAttempts = 45
      const pollMessages = [
        'Scraping pricing page...',
        'Reading pricing details...',
        'Analyzing with AI...',
        'Extracting plan data...',
        'Almost done...',
      ]

      const interval = setInterval(async () => {
        attempts++
        setStatusText(pollMessages[Math.min(Math.floor(attempts / 5), pollMessages.length - 1)])

        if (attempts >= maxAttempts) {
          clearInterval(interval)
          setPhase('error')
          setError('Analysis is taking too long. Please try again.')
          return
        }

        try {
          const analysis = await getAnalysis(id)
          if (!analysis) return

          if (analysis.status === 'done') {
            clearInterval(interval)
            router.push(`/analyze/${id}`)
          } else if (analysis.status === 'failed') {
            clearInterval(interval)
            setPhase('error')
            setError('Failed to analyze this URL. Make sure it has a pricing page.')
          }
        } catch {
          // Ignore network errors during polling
        }
      }, 2000)
    } catch (err: any) {
      setPhase('error')
      setError(err.message ?? 'Something went wrong. Please try again.')
    }
  }

  const isLoading = phase === 'submitting' || phase === 'polling'

  return (
    <form onSubmit={handleSubmit} className="w-full">
      <div className="flex gap-0 bg-white border-2 border-gray-200 rounded-2xl shadow-md focus-within:border-blue-500 focus-within:shadow-lg transition-all overflow-hidden">
        <input
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="stripe.com/pricing"
          disabled={isLoading}
          autoFocus
          className="flex-1 px-5 py-4 text-lg text-gray-900 placeholder-gray-400 bg-transparent outline-none disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={isLoading || !url.trim()}
          className="flex items-center gap-2 px-7 py-4 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold transition-colors text-base whitespace-nowrap"
        >
          {isLoading ? (
            <>
              <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Analyzing
            </>
          ) : (
            'Analyze →'
          )}
        </button>
      </div>

      {isLoading && (
        <p className="mt-3 text-sm text-center text-gray-500 animate-pulse">{statusText}</p>
      )}

      {phase === 'error' && (
        <p className="mt-3 text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl px-4 py-3">
          {error}
        </p>
      )}
    </form>
  )
}

export default function AnalyzeForm() {
  return (
    <Suspense fallback={<div className="h-16" />}>
      <AnalyzeFormInner />
    </Suspense>
  )
}
