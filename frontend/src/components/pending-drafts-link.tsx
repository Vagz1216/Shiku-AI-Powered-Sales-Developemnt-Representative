'use client'

import { useAuth } from '@clerk/clerk-react'
import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'
import { useTenantScope } from '@/components/tenant-scope'
import { fetchWithAuthRetry } from '@/lib/auth-fetch'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface PendingDraftsLinkProps {
  active?: boolean
  className?: string
}

export function PendingDraftsLink({ active = false, className }: PendingDraftsLinkProps) {
  const { isLoaded, userId, getToken } = useAuth()
  const { selectedOrganizationId, orgUrl } = useTenantScope()
  const [count, setCount] = useState(0)

  const loadCount = useCallback(async () => {
    if (!isLoaded || !userId || !selectedOrganizationId) return
    try {
      const res = await fetchWithAuthRetry(getToken, orgUrl(`${API_BASE}/api/drafts`))
      if (!res.ok) return
      const data = (await res.json()) as { drafts?: unknown[] }
      setCount((data.drafts || []).length)
    } catch {
      setCount(0)
    }
  }, [getToken, isLoaded, orgUrl, selectedOrganizationId, userId])

  useEffect(() => {
    const initial = window.setTimeout(() => {
      void loadCount()
    }, 0)
    const interval = window.setInterval(() => {
      void loadCount()
    }, 30000)
    const handleFocus = () => {
      void loadCount()
    }
    window.addEventListener('focus', handleFocus)
    window.addEventListener('sdr:organization-changed', handleFocus)
    return () => {
      window.clearTimeout(initial)
      window.clearInterval(interval)
      window.removeEventListener('focus', handleFocus)
      window.removeEventListener('sdr:organization-changed', handleFocus)
    }
  }, [loadCount])

  const labelClass = active
    ? 'text-sm font-medium text-zinc-900 dark:text-zinc-100'
    : 'text-sm text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100'

  const badgeLabel = count > 99 ? '99+' : String(count)

  return (
    <Link
      href="/drafts"
      className={className ?? `inline-flex items-center gap-1.5 ${labelClass}`}
      aria-label={count > 0 ? `Drafts, ${count} pending review` : 'Drafts'}
    >
      <span>Drafts</span>
      {count > 0 && (
        <span className="inline-flex min-w-5 h-5 items-center justify-center rounded-full bg-rose-600 px-1.5 text-[11px] font-semibold leading-none text-white">
          {badgeLabel}
        </span>
      )}
    </Link>
  )
}
