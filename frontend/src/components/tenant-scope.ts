'use client'

import { useAuth } from '@clerk/clerk-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const STORAGE_KEY = 'sdr:selectedOrganizationId'
const EVENT_NAME = 'sdr:organization-changed'

export interface OrganizationCapabilities {
  can_create_organizations: boolean
  can_manage_subscription_plans: boolean
  can_choose_subscription_plan: boolean
  can_manage_organization: boolean
  can_manage_users: boolean
  can_manage_mailboxes: boolean
  can_manage_staff: boolean
  can_manage_campaigns: boolean
  can_manage_leads: boolean
  can_review_drafts: boolean
  can_run_outreach: boolean
  can_view_compliance: boolean
}

export interface SubscriptionPlan {
  id: number
  name: string
  slug: string
  description: string | null
  monthly_price_cents: number
  trial_days: number
  max_users: number | null
  max_campaigns: number | null
  max_leads: number | null
  max_monthly_emails: number | null
  max_monthly_ai_tokens: number | null
  max_monthly_ai_credits: number | null
  overage_allowed: boolean
  overage_price_cents_per_ai_credit: number | null
  active: boolean
  created_at: string
  updated_at: string | null
}

export interface OrganizationSubscription {
  id?: number
  organization_id?: number
  status: string
  effective_status: string
  is_active: boolean
  trial_ends_at?: string | null
  current_period_started_at?: string | null
  current_period_ends_at?: string | null
  created_at?: string
  updated_at?: string | null
  plan: SubscriptionPlan | null
}

export interface TenantOrganization {
  id: number
  name: string
  slug: string
  timezone: string
  status: string
  current_user_role: string
  capabilities?: OrganizationCapabilities
  subscription?: OrganizationSubscription
}

export function notifyOrganizationChanged(organizationId: number) {
  window.localStorage.setItem(STORAGE_KEY, String(organizationId))
  window.dispatchEvent(new CustomEvent(EVENT_NAME, { detail: { organizationId } }))
}

export function appendOrganizationParam(url: string, organizationId?: number | null) {
  if (!organizationId) return url
  const nextUrl = new URL(url)
  nextUrl.searchParams.set('organization_id', String(organizationId))
  return nextUrl.toString()
}

export function useTenantScope() {
  const { isLoaded, userId, getToken } = useAuth()
  const [organizations, setOrganizations] = useState<TenantOrganization[]>([])
  const [selectedOrganizationId, setSelectedOrganizationId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)

  const loadOrganizations = useCallback(async () => {
    if (!isLoaded || !userId) return
    setLoading(true)
    try {
      const token = await getToken()
      const res = await fetch(`${API_BASE}/api/me`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) {
        setOrganizations([])
        setSelectedOrganizationId(null)
        return
      }
      const data = await res.json() as { organizations?: TenantOrganization[] }
      const orgs = data.organizations || []
      setOrganizations(orgs)
      const stored = Number(window.localStorage.getItem(STORAGE_KEY) || 0)
      const selected = orgs.find(org => org.id === stored) || orgs[0] || null
      setSelectedOrganizationId(selected?.id || null)
      if (selected) {
        window.localStorage.setItem(STORAGE_KEY, String(selected.id))
      }
    } finally {
      setLoading(false)
    }
  }, [getToken, isLoaded, userId])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadOrganizations()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadOrganizations])

  useEffect(() => {
    const onChange = (event: Event) => {
      const custom = event as CustomEvent<{ organizationId?: number }>
      const next = custom.detail?.organizationId || Number(window.localStorage.getItem(STORAGE_KEY) || 0)
      if (next) setSelectedOrganizationId(next)
      void loadOrganizations()
    }
    window.addEventListener(EVENT_NAME, onChange)
    return () => window.removeEventListener(EVENT_NAME, onChange)
  }, [loadOrganizations])

  const selectedOrganization = useMemo(
    () => organizations.find(org => org.id === selectedOrganizationId) || organizations[0] || null,
    [organizations, selectedOrganizationId],
  )

  const setSelectedOrganization = useCallback((organizationId: number) => {
    setSelectedOrganizationId(organizationId)
    notifyOrganizationChanged(organizationId)
  }, [])

  const orgUrl = useCallback((url: string) => appendOrganizationParam(url, selectedOrganizationId), [selectedOrganizationId])

  return {
    loading,
    organizations,
    selectedOrganization,
    selectedOrganizationId,
    setSelectedOrganization,
    reloadOrganizations: loadOrganizations,
    orgUrl,
  }
}
