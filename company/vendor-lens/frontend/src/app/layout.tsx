import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'VendorLens — Instant SaaS Pricing Intelligence',
  description: 'Paste a vendor URL and get instant structured pricing analysis, cost projections, and risk flags. Decision clarity for indie devs and small teams.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans antialiased text-gray-900">
        {children}
      </body>
    </html>
  )
}
