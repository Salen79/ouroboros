'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'

export default function CompareButton({ analysisId, vendorName }: { analysisId: string; vendorName: string }) {
  const [inCart, setInCart] = useState(false)
  const router = useRouter()

  function toggle() {
    const stored = JSON.parse(localStorage.getItem('vl_compare') ?? '[]') as string[]
    if (inCart) {
      localStorage.setItem('vl_compare', JSON.stringify(stored.filter((x) => x !== analysisId)))
    } else {
      if (stored.length >= 3) {
        alert('You can compare up to 3 vendors at once.')
        return
      }
      stored.push(analysisId)
      localStorage.setItem('vl_compare', JSON.stringify(stored))
    }
    setInCart(!inCart)
  }

  function goCompare() {
    const stored = JSON.parse(localStorage.getItem('vl_compare') ?? '[]') as string[]
    if (stored.length < 2) {
      alert('Add at least 2 vendors to compare.')
      return
    }
    router.push(`/compare?ids=${stored.join(',')}`)
  }

  return (
    <div className="flex gap-2">
      <button
        onClick={toggle}
        className={`px-3 py-2 rounded-xl border text-sm font-medium transition-colors ${
          inCart
            ? 'bg-blue-600 border-blue-600 text-white'
            : 'bg-white border-gray-200 text-gray-700 hover:border-blue-400'
        }`}
      >
        {inCart ? '✓ In compare' : '+ Compare'}
      </button>
      <button
        onClick={goCompare}
        className="px-3 py-2 rounded-xl border border-gray-200 text-gray-700 text-sm font-medium hover:border-blue-400 transition-colors bg-white"
      >
        View Compare
      </button>
    </div>
  )
}
