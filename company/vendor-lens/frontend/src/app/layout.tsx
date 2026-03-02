import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'VendorLens — Instant SaaS Pricing Intelligence',
  description: 'Paste a pricing URL, get a structured breakdown of plans, limits, hidden costs and risks. Free, instant, no login.',
  metadataBase: new URL('https://vendorlens.app'),
  openGraph: {
    title: 'VendorLens — Instant SaaS Pricing Intelligence',
    description: 'Paste a pricing URL, get a structured breakdown of plans, limits, hidden costs and risks. Free, instant, no login.',
    url: 'https://vendorlens.app',
    siteName: 'VendorLens',
    locale: 'en_US',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'VendorLens — Instant SaaS Pricing Intelligence',
    description: 'Paste a pricing URL, get a structured breakdown of plans, limits, hidden costs and risks. Free, instant, no login.',
    creator: '@vendorlens',
  },
  alternates: {
    canonical: 'https://vendorlens.app',
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
    },
  },
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
