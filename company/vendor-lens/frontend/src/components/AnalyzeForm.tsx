'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { submitAnalysis, getAnalysis } from '@/lib/api'

type Phase = 'idle' | 'submitting' | 'polling' | 'error'

export default function AnalyzeForm() {
  const [url, setUrl] = useState('')
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState('')
  const [statusText, setStatusText] = useState('')
  const router = useRouter()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = url.trim()
    if (!trimmed) return

    // Normalise: add https:// if missing
    const normalised = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`

    setPhase('submitting')
    setError('')
    setStatusText('Submitting...')

    try {
      const { id } = await submitAnalysis(normalised)
      setPhase('polling')
      setStatusText('Scraping pricing page...')

      // Poll every 2 s until done or failed
      let attempts = 0
      const maxAttempts = 45 // 90 seconds max
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
    <form onSubmit={handleSubmit} className="w-full max-w-xl mx-auto">
      <div className="flex gap-2 p-1.5 bg-white border border-gray-200 rounded-xl shadow-sm focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-100 transition-all">
        <input
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="stripe.com/pricing"
          disabled={isLoading}
          className="flex-1 px-3 py-2.5 text-base text-gray-900 placeholder-gray-400 bg-transparent outline-none disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={isLoading || !url.trim()}
          className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-lg transition-colors text-sm"
        >
          {isLoading ? (
            <>
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Analyzing
            </>
          ) : (
            <>Analyze &rarr;</>
          )}
        </button>
      </div>

      {isLoading && (
        <p className="mt-3 text-sm text-gray-500 animate-pulse">{statusText}</p>
      )}

      {phase === 'error' && (
        <p className="mt-3 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {error}
        </p>
      )}
    </form>
  )
}
