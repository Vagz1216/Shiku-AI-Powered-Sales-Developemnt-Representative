'use client'

import { useAuth } from '@clerk/clerk-react'
import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'
import { useTenantScope } from '@/components/tenant-scope'
import { fetchWithAuthRetry } from '@/lib/auth-fetch'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const DRAFT_COUNT_CACHE_TTL_MS = 15_000

const draftCountCache = new Map<number, { count: number; expiresAt: number }>()
const draftCountInflight = new Map<number, Promise<number>>()

interface PendingDraftsLinkProps {
  active?: boolean
  className?: string
}

export function PendingDraftsLink({ active = false, className }: PendingDraftsLinkProps) {
  const { isLoaded, userId, getToken } = useAuth()
  const { selectedOrganizationId, orgUrl } = useTenantScope()
  const [count, setCount] = useState(0)

  const loadCount = useCallback(async () => {
    if (active || !isLoaded || !userId || !selectedOrganizationId) return
    const cached = draftCountCache.get(selectedOrganizationId)
    if (cached && cached.expiresAt > Date.now()) {
      setCount(cached.count)
      return
    }
    try {
      let request = draftCountInflight.get(selectedOrganizationId)
      if (!request) {
        request = (async () => {
          const res = await fetchWithAuthRetry(getToken, orgUrl(`${API_BASE}/api/drafts/count`))
          if (!res.ok) return cached?.count || 0
          const data = (await res.json()) as { count?: number }
          const nextCount = Number(data.count || 0)
          draftCountCache.set(selectedOrganizationId, {
            count: nextCount,
            expiresAt: Date.now() + DRAFT_COUNT_CACHE_TTL_MS,
          })
          return nextCount
        })().finally(() => {
          draftCountInflight.delete(selectedOrganizationId)
        })
        draftCountInflight.set(selectedOrganizationId, request)
      }
      setCount(await request)
    } catch {
      setCount(0)
    }
  }, [active, getToken, isLoaded, orgUrl, selectedOrganizationId, userId])

  useEffect(() => {
    if (active) {
      return
    }
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
  }, [active, loadCount])

  const labelClass = active
    ? 'text-sm font-medium text-zinc-900 dark:text-zinc-100'
    : 'text-sm text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100'

  const visibleCount = active ? 0 : count
  const badgeLabel = visibleCount > 99 ? '99+' : String(visibleCount)

  return (
    <Link
      href="/drafts"
      className={className ?? `inline-flex items-center gap-1.5 ${labelClass}`}
      aria-label={visibleCount > 0 ? `Drafts, ${visibleCount} pending review` : 'Drafts'}
    >
      <span>Drafts</span>
      {visibleCount > 0 && (
        <span className="inline-flex min-w-5 h-5 items-center justify-center rounded-full bg-rose-600 px-1.5 text-[11px] font-semibold leading-none text-white">
          {badgeLabel}
        </span>
      )}
    </Link>
  )
}
