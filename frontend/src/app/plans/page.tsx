'use client'

import { useAuth } from '@clerk/clerk-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { AppShell } from '@/components/app-shell'
import { SubscriptionPlan, useTenantScope } from '@/components/tenant-scope'
import { fetchWithAuthRetry } from '@/lib/auth-fetch'
import { formatDate } from '@/lib/time'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface PlanFormState {
  name: string
  slug: string
  description: string
  monthly_price: string
  currency_code: string
  market_code: string
  trial_days: string
  max_users: string
  max_campaigns: string
  max_leads: string
  max_monthly_emails: string
  max_monthly_ai_tokens: string
  max_monthly_ai_credits: string
  overage_allowed: boolean
  overage_price_cents_per_ai_credit: string
  allow_byok: boolean
  byok_provider_mode: 'platform_first' | 'organization_first' | 'organization_only'
  max_llm_credentials: string
  allowed_llm_routing_modes: Array<'quality_first' | 'balanced' | 'cost_optimized'>
  default_llm_routing_mode: 'quality_first' | 'balanced' | 'cost_optimized'
  trial_allowed_llm_routing_modes: Array<'quality_first' | 'balanced' | 'cost_optimized'>
  active: boolean
}

const ROUTING_MODES: Array<'cost_optimized' | 'balanced' | 'quality_first'> = ['cost_optimized', 'balanced', 'quality_first']

const ROUTING_MODE_REFERENCE = [
  {
    mode: 'cost_optimized',
    label: 'Cost optimized',
    creditMultiplier: '1x credits',
    summary: 'Uses lower-cost capable providers first for routine, high-volume work. This is the default trial-safe mode.',
    writingOrder: 'Gemini Flash, Cerebras GPT-OSS, then Azure/OpenAI mini models',
    structuredOrder: 'Cerebras GPT-OSS first, then Gemini Flash; Azure/OpenAI if stricter schema reliability is needed',
    byokExamples: 'gemini-2.5-flash, gpt-oss-120b, gpt-4o-mini, gpt-4.1-mini',
  },
  {
    mode: 'balanced',
    label: 'Balanced',
    creditMultiplier: '2x credits',
    summary: 'The recommended production middle ground: strong quality with cheaper capable providers before premium fallback.',
    writingOrder: 'Gemini Flash first, then Azure/OpenAI mini models, then compatible fallbacks',
    structuredOrder: 'Gemini Flash first, then Cerebras; Azure/OpenAI when review strictness matters',
    byokExamples: 'gemini-2.5-flash, gpt-4o-mini, gpt-4.1-mini, gpt-oss-120b',
  },
  {
    mode: 'quality_first',
    label: 'Quality first',
    creditMultiplier: '4x credits',
    summary: 'Premium-first routing for sensitive or high-value user-facing communication. It consumes credits faster.',
    writingOrder: 'Azure/OpenAI first; Claude via OpenRouter can be used for high-quality writing when configured',
    structuredOrder: 'Azure/OpenAI first; Gemini/Cerebras as capable fallbacks. Keep safety and sender flows on validated models.',
    byokExamples: 'gpt-4.1, gpt-4.1-mini, gpt-4o, gpt-4o-mini, anthropic/claude-sonnet-4.6 via OpenRouter',
  },
] as const

function emptyPlanForm(): PlanFormState {
  return {
    name: '',
    slug: '',
    description: '',
    monthly_price: '0',
    currency_code: 'USD',
    market_code: 'GLOBAL',
    trial_days: '14',
    max_users: '',
    max_campaigns: '',
    max_leads: '',
    max_monthly_emails: '',
    max_monthly_ai_tokens: '',
    max_monthly_ai_credits: '',
    overage_allowed: false,
    overage_price_cents_per_ai_credit: '',
    allow_byok: false,
    byok_provider_mode: 'platform_first',
    max_llm_credentials: '',
    allowed_llm_routing_modes: ['cost_optimized', 'balanced', 'quality_first'],
    default_llm_routing_mode: 'balanced',
    trial_allowed_llm_routing_modes: ['cost_optimized'],
    active: true,
  }
}

function centsFromPrice(value: string) {
  const parsed = Number(value || 0)
  if (!Number.isFinite(parsed) || parsed < 0) return 0
  return Math.round(parsed * 100)
}

function optionalNumber(value: string) {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : null
}

function formatMoney(cents: number, currency = 'USD') {
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency,
      maximumFractionDigits: 0,
    }).format((cents || 0) / 100)
  } catch {
    return `${currency} ${new Intl.NumberFormat('en-US').format((cents || 0) / 100)}`
  }
}

function formatLimit(value: number | null) {
  return value ? new Intl.NumberFormat('en-US').format(value) : 'Unlimited'
}

function getErrorMessage(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback
}

function routingModesArray(modes: string[] | string | undefined | null) {
  if (Array.isArray(modes)) return modes
  if (typeof modes === 'string') {
    return modes.split(',').map(mode => mode.trim()).filter(Boolean)
  }
  return []
}

function formatRoutingModes(modes: string[] | string | undefined | null) {
  return routingModesArray(modes).map(mode => mode.replace('_', ' ')).join(', ') || 'None'
}

function statusClass(status?: string) {
  const normalized = (status || 'NONE').toUpperCase()
  if (normalized === 'ACTIVE' || normalized === 'TRIALING') {
    return 'bg-emerald-50 text-emerald-700 ring-emerald-600/20 dark:bg-emerald-950 dark:text-emerald-300'
  }
  if (normalized === 'PAST_DUE') {
    return 'bg-amber-50 text-amber-700 ring-amber-600/20 dark:bg-amber-950 dark:text-amber-300'
  }
  return 'bg-zinc-100 text-zinc-700 ring-zinc-600/20 dark:bg-zinc-800 dark:text-zinc-300'
}

function toggleRoutingMode(
  modes: PlanFormState['allowed_llm_routing_modes'],
  mode: PlanFormState['default_llm_routing_mode'],
) {
  return modes.includes(mode) ? modes.filter(item => item !== mode) : [...modes, mode]
}

export default function PlansPage() {
  const { isLoaded, userId, getToken } = useAuth()
  const {
    loading,
    selectedOrganization,
    selectedOrganizationId,
    reloadOrganizations,
  } = useTenantScope()
  const [plans, setPlans] = useState<SubscriptionPlan[]>([])
  const [form, setForm] = useState<PlanFormState>(() => emptyPlanForm())
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [subscriptionStatusOverride, setSubscriptionStatusOverride] = useState<{ orgId: number | null, status: string } | null>(null)

  const capabilities = selectedOrganization?.capabilities
  const canManagePlans = !!capabilities?.can_manage_subscription_plans
  const canChoosePlan = !!capabilities?.can_choose_subscription_plan
  const currentPlanId = selectedOrganization?.subscription?.plan?.id || null

  const authedFetch = useCallback(async (url: string, init: RequestInit = {}) => {
    return fetchWithAuthRetry(getToken, url, init)
  }, [getToken])

  const loadPlans = useCallback(async () => {
    if (!isLoaded || !userId) return
    setError('')
    try {
      const res = await authedFetch(`${API_BASE}/api/plans`)
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed to load plans')
      const data = await res.json() as { plans?: SubscriptionPlan[] }
      setPlans(data.plans || [])
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load plans'))
    }
  }, [authedFetch, isLoaded, userId])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadPlans()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadPlans])

  const subscriptionStatus =
    subscriptionStatusOverride?.orgId === selectedOrganizationId
      ? subscriptionStatusOverride.status
      : selectedOrganization?.subscription?.status || 'ACTIVE'

  const createPlan = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!canManagePlans) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const res = await authedFetch(`${API_BASE}/api/plans`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: form.name,
          slug: form.slug || null,
          description: form.description || null,
          monthly_price_cents: centsFromPrice(form.monthly_price),
          currency_code: form.currency_code,
          market_code: form.market_code,
          trial_days: Number(form.trial_days || 0),
          max_users: optionalNumber(form.max_users),
          max_campaigns: optionalNumber(form.max_campaigns),
          max_leads: optionalNumber(form.max_leads),
          max_monthly_emails: optionalNumber(form.max_monthly_emails),
          max_monthly_ai_tokens: optionalNumber(form.max_monthly_ai_tokens),
          max_monthly_ai_credits: optionalNumber(form.max_monthly_ai_credits),
          overage_allowed: form.overage_allowed,
          overage_price_cents_per_ai_credit: optionalNumber(form.overage_price_cents_per_ai_credit),
          allow_byok: form.allow_byok,
          byok_provider_mode: form.byok_provider_mode,
          max_llm_credentials: optionalNumber(form.max_llm_credentials),
          allowed_llm_routing_modes: form.allowed_llm_routing_modes,
          default_llm_routing_mode: form.default_llm_routing_mode,
          trial_allowed_llm_routing_modes: form.trial_allowed_llm_routing_modes,
          active: form.active,
        }),
      })
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed to create plan')
      setForm(emptyPlanForm())
      setNotice('Plan created.')
      await loadPlans()
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to create plan'))
    } finally {
      setBusy(false)
    }
  }

  const updatePlanActive = async (plan: SubscriptionPlan, active: boolean) => {
    if (!canManagePlans) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const res = await authedFetch(`${API_BASE}/api/plans/${plan.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active }),
      })
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed to update plan')
      setNotice(active ? 'Plan activated.' : 'Plan archived.')
      await loadPlans()
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to update plan'))
    } finally {
      setBusy(false)
    }
  }

  const updatePlanByok = async (plan: SubscriptionPlan, patch: Partial<Pick<SubscriptionPlan, 'allow_byok' | 'byok_provider_mode'>>) => {
    if (!canManagePlans) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const res = await authedFetch(`${API_BASE}/api/plans/${plan.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Failed to update BYOK settings')
      setPlans(items => items.map(item => item.id === plan.id ? data.plan : item))
      setNotice('Plan BYOK settings updated.')
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to update BYOK settings'))
    } finally {
      setBusy(false)
    }
  }

  const updatePlanRouting = async (
    plan: SubscriptionPlan,
    patch: Partial<Pick<SubscriptionPlan, 'allowed_llm_routing_modes' | 'default_llm_routing_mode' | 'trial_allowed_llm_routing_modes'>>,
  ) => {
    if (!canManagePlans) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const res = await authedFetch(`${API_BASE}/api/plans/${plan.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Failed to update routing settings')
      setPlans(items => items.map(item => item.id === plan.id ? data.plan : item))
      setNotice('Plan routing settings updated.')
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to update routing settings'))
    } finally {
      setBusy(false)
    }
  }

  const choosePlan = async (plan: SubscriptionPlan) => {
    if (!selectedOrganizationId || !canChoosePlan || !plan.active) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const res = await authedFetch(`${API_BASE}/api/organizations/${selectedOrganizationId}/subscription`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan_id: plan.id }),
      })
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed to choose plan')
      setNotice(`${plan.name} selected for ${selectedOrganization?.name || 'organization'}.`)
      await reloadOrganizations()
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to choose plan'))
    } finally {
      setBusy(false)
    }
  }

  const updateSubscriptionStatus = async () => {
    if (!selectedOrganizationId || !canManagePlans) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const res = await authedFetch(`${API_BASE}/api/organizations/${selectedOrganizationId}/subscription`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: subscriptionStatus }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Failed to update subscription')
      setNotice(`Subscription marked ${subscriptionStatus}.`)
      setSubscriptionStatusOverride(null)
      await reloadOrganizations()
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to update subscription'))
    } finally {
      setBusy(false)
    }
  }

  const sortedPlans = useMemo(
    () => [...plans].sort((a, b) => a.monthly_price_cents - b.monthly_price_cents || a.id - b.id),
    [plans],
  )

  if (!isLoaded || !userId || loading) {
    return <div className="flex min-h-screen items-center justify-center">Loading or unauthorized...</div>
  }

  return (
    <AppShell active="plans">
      <main className="mx-auto w-full max-w-[96rem] p-6 lg:p-8">
        <div className="mb-6 flex flex-col gap-2">
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Plans</h1>
          <p className="text-sm text-zinc-500">
            {selectedOrganization?.name || 'Selected organization'} · {selectedOrganization?.subscription?.effective_status || 'NONE'}
          </p>
        </div>

        {error && <div className="mb-4 rounded-md bg-rose-100 p-4 text-sm text-rose-700">{error}</div>}
        {notice && <div className="mb-4 rounded-md bg-emerald-100 p-4 text-sm text-emerald-800">{notice}</div>}

        {canChoosePlan && (
          <section className="mb-6 rounded-lg border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            <div className="border-b border-zinc-200 px-5 py-3 dark:border-zinc-800">
              <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                <div>
                  <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">Assign Plan</h2>
                  <p className="mt-1 text-sm text-zinc-500">
                    Target: {selectedOrganization?.name || 'No organization selected'}
                  </p>
                </div>
                <span className={`w-fit rounded-full px-2 py-1 text-xs font-medium ring-1 ring-inset ${statusClass(selectedOrganization?.subscription?.effective_status)}`}>
                  {selectedOrganization?.subscription?.effective_status || 'NONE'}
                </span>
              </div>
            </div>
            <div className="grid gap-3 p-5 md:grid-cols-2 xl:grid-cols-4">
              {sortedPlans.filter(plan => plan.active).map(plan => {
                const selected = currentPlanId === plan.id
                return (
                  <div key={plan.id} className={`rounded-md border p-4 ${selected ? 'border-zinc-900 bg-zinc-50 dark:border-zinc-100 dark:bg-zinc-800' : 'border-zinc-200 dark:border-zinc-800'}`}>
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <h3 className="font-medium text-zinc-900 dark:text-zinc-100">{plan.name}</h3>
                        <div className="mt-1 text-xs text-zinc-500">{plan.slug}</div>
                      </div>
                      <div className="text-sm font-medium">{formatMoney(plan.monthly_price_cents, plan.currency_code)}</div>
                    </div>
                    <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-zinc-600 dark:text-zinc-300">
                      <div>Users {formatLimit(plan.max_users)}</div>
                      <div>Leads {formatLimit(plan.max_leads)}</div>
                      <div>Emails {formatLimit(plan.max_monthly_emails)}</div>
                      <div>Credits {formatLimit(plan.max_monthly_ai_credits)}</div>
                    </div>
                    <div className="mt-3 text-xs text-zinc-500">
                      Default routing: {plan.default_llm_routing_mode.replace('_', ' ')}
                    </div>
                    <button
                      type="button"
                      onClick={() => void choosePlan(plan)}
                      disabled={busy || selected}
                      className="mt-4 w-full rounded-md bg-zinc-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
                    >
                      {selected ? 'Currently assigned' : `Assign ${plan.name}`}
                    </button>
                  </div>
                )
              })}
            </div>
          </section>
        )}

        <section className="mb-6 rounded-lg border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <div className="border-b border-zinc-200 px-5 py-3 dark:border-zinc-800">
            <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">LLM Routing Reference</h2>
            <p className="mt-1 text-sm text-zinc-500">
              Routing modes control provider priority and credit burn. Actual order can vary by agent when schema, safety, or tool-calling support is required.
            </p>
          </div>
          <div className="grid gap-3 p-5 lg:grid-cols-3">
            {ROUTING_MODE_REFERENCE.map(reference => (
              <div key={reference.mode} className="rounded-md border border-zinc-200 p-4 dark:border-zinc-800">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="font-medium text-zinc-900 dark:text-zinc-100">{reference.label}</h3>
                    <div className="mt-1 text-xs uppercase tracking-wide text-zinc-500">{reference.mode.replace('_', ' ')}</div>
                  </div>
                  <span className="rounded-full bg-zinc-100 px-2 py-1 text-xs font-medium text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                    {reference.creditMultiplier}
                  </span>
                </div>
                <p className="mt-3 text-sm leading-6 text-zinc-600 dark:text-zinc-300">{reference.summary}</p>
                <dl className="mt-4 space-y-3 text-sm">
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-zinc-500">Drafting and replies</dt>
                    <dd className="mt-1 text-zinc-700 dark:text-zinc-300">{reference.writingOrder}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-zinc-500">Review and classification</dt>
                    <dd className="mt-1 text-zinc-700 dark:text-zinc-300">{reference.structuredOrder}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-zinc-500">BYOK model examples</dt>
                    <dd className="mt-1 text-zinc-700 dark:text-zinc-300">{reference.byokExamples}</dd>
                  </div>
                </dl>
              </div>
            ))}
          </div>
        </section>

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
          <section className="space-y-6">
            <div className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
              <h2 className="text-base font-semibold">Current Plan</h2>
              <div className="mt-4 space-y-2 text-sm text-zinc-700 dark:text-zinc-300">
                <div className="flex justify-between gap-4">
                  <span className="text-zinc-500">Plan</span>
                  <span className="font-medium text-zinc-900 dark:text-zinc-100">{selectedOrganization?.subscription?.plan?.name || 'None'}</span>
                </div>
                <div className="flex justify-between gap-4">
                  <span className="text-zinc-500">Status</span>
                  <span>{selectedOrganization?.subscription?.effective_status || 'NONE'}</span>
                </div>
                <div className="flex justify-between gap-4">
                  <span className="text-zinc-500">Trial Ends</span>
                  <span>{formatDate(selectedOrganization?.subscription?.trial_ends_at, selectedOrganization?.timezone)}</span>
                </div>
                <div className="flex justify-between gap-4">
                  <span className="text-zinc-500">Period Ends</span>
                  <span>{formatDate(selectedOrganization?.subscription?.current_period_ends_at, selectedOrganization?.timezone)}</span>
                </div>
              </div>
              {canManagePlans && (
                <div className="mt-4 border-t border-zinc-200 pt-4 dark:border-zinc-800">
                  <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                    Manual subscription status
                    <select
                      value={subscriptionStatus}
                      onChange={e => setSubscriptionStatusOverride({ orgId: selectedOrganizationId, status: e.target.value })}
                      className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
                    >
                      <option value="TRIALING">TRIALING</option>
                      <option value="ACTIVE">ACTIVE</option>
                      <option value="PAST_DUE">PAST_DUE</option>
                      <option value="CANCELED">CANCELED</option>
                      <option value="EXPIRED">EXPIRED</option>
                    </select>
                  </label>
                  <button
                    type="button"
                    onClick={() => void updateSubscriptionStatus()}
                    disabled={busy || !selectedOrganization?.subscription?.plan}
                    className="mt-3 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm font-medium disabled:opacity-50 dark:border-zinc-700"
                  >
                    Update Status
                  </button>
                  <p className="mt-2 text-xs text-zinc-500">
                    PAST_DUE, CANCELED, and EXPIRED block paid workflows while keeping read-only access.
                  </p>
                </div>
              )}
            </div>

            {canManagePlans && (
              <form onSubmit={createPlan} className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
                <h2 className="text-base font-semibold">Create Plan</h2>
                <div className="mt-4 space-y-3">
                  <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                    Plan name
                    <input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} required placeholder="Growth" className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                  </label>
                  <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                    Plan slug
                    <input value={form.slug} onChange={e => setForm({ ...form, slug: e.target.value })} placeholder="growth" className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                  </label>
                  <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                    Description
                    <textarea value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} placeholder="For small SDR teams testing outbound workflows" rows={3} className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                  </label>
                  <div className="grid grid-cols-2 gap-3">
                    <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                      Monthly price
                      <input value={form.monthly_price} onChange={e => setForm({ ...form, monthly_price: e.target.value })} type="number" min="0" step="1" placeholder="49" className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                    </label>
                    <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                      Trial days
                      <input value={form.trial_days} onChange={e => setForm({ ...form, trial_days: e.target.value })} type="number" min="0" placeholder="14" className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                    </label>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                      Currency
                      <input value={form.currency_code} onChange={e => setForm({ ...form, currency_code: e.target.value.toUpperCase() })} maxLength={3} placeholder="USD" className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm uppercase dark:border-zinc-700 dark:bg-zinc-800" />
                    </label>
                    <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                      Market
                      <input value={form.market_code} onChange={e => setForm({ ...form, market_code: e.target.value.toUpperCase() })} maxLength={16} placeholder="KE" className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm uppercase dark:border-zinc-700 dark:bg-zinc-800" />
                    </label>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                      Max users
                      <input value={form.max_users} onChange={e => setForm({ ...form, max_users: e.target.value })} type="number" min="1" placeholder="10" className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                    </label>
                    <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                      Max campaigns
                      <input value={form.max_campaigns} onChange={e => setForm({ ...form, max_campaigns: e.target.value })} type="number" min="1" placeholder="25" className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                    </label>
                    <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                      Max leads
                      <input value={form.max_leads} onChange={e => setForm({ ...form, max_leads: e.target.value })} type="number" min="1" placeholder="5000" className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                    </label>
                    <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                      Monthly emails
                      <input value={form.max_monthly_emails} onChange={e => setForm({ ...form, max_monthly_emails: e.target.value })} type="number" min="1" placeholder="2000" className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                    </label>
                  </div>
                  <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                    Monthly AI tokens
                    <input value={form.max_monthly_ai_tokens} onChange={e => setForm({ ...form, max_monthly_ai_tokens: e.target.value })} type="number" min="1" placeholder="1000000" className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                  </label>
                  <div className="grid grid-cols-2 gap-3">
                    <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                      Monthly AI credits
                      <input value={form.max_monthly_ai_credits} onChange={e => setForm({ ...form, max_monthly_ai_credits: e.target.value })} type="number" min="1" placeholder="5000" className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                    </label>
                    <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                      Overage cents / credit
                      <input value={form.overage_price_cents_per_ai_credit} onChange={e => setForm({ ...form, overage_price_cents_per_ai_credit: e.target.value })} type="number" min="1" placeholder="2" className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                    </label>
                  </div>
                  <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
                    <input type="checkbox" checked={form.overage_allowed} onChange={e => setForm({ ...form, overage_allowed: e.target.checked })} />
                    Allow AI credit overage
                  </label>
                  <div className="rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
                    <div className="text-sm font-medium text-zinc-700 dark:text-zinc-300">LLM routing entitlements</div>
                    <div className="mt-3 grid gap-2">
                      {ROUTING_MODES.map(mode => (
                        <label key={mode} className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
                          <input
                            type="checkbox"
                            checked={form.allowed_llm_routing_modes.includes(mode)}
                            onChange={() => setForm({ ...form, allowed_llm_routing_modes: toggleRoutingMode(form.allowed_llm_routing_modes, mode) })}
                          />
                          Paid: {mode.replace('_', ' ')}
                        </label>
                      ))}
                    </div>
                    <label className="mt-3 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                      Default paid mode
                      <select
                        value={form.default_llm_routing_mode}
                        onChange={e => setForm({ ...form, default_llm_routing_mode: e.target.value as PlanFormState['default_llm_routing_mode'] })}
                        className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
                      >
                        {ROUTING_MODES.map(mode => <option key={mode} value={mode}>{mode.replace('_', ' ')}</option>)}
                      </select>
                    </label>
                    <div className="mt-3 grid gap-2">
                      {ROUTING_MODES.map(mode => (
                        <label key={mode} className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
                          <input
                            type="checkbox"
                            checked={form.trial_allowed_llm_routing_modes.includes(mode)}
                            onChange={() => setForm({ ...form, trial_allowed_llm_routing_modes: toggleRoutingMode(form.trial_allowed_llm_routing_modes, mode) })}
                          />
                          Trial: {mode.replace('_', ' ')}
                        </label>
                      ))}
                    </div>
                  </div>
                  <div className="rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
                    <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
                      <input type="checkbox" checked={form.allow_byok} onChange={e => setForm({ ...form, allow_byok: e.target.checked })} />
                      Allow organization-managed LLM keys
                    </label>
                    <div className="mt-3 grid grid-cols-1 gap-3">
                      <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                        BYOK routing
                        <select
                          value={form.byok_provider_mode}
                          onChange={e => setForm({ ...form, byok_provider_mode: e.target.value as PlanFormState['byok_provider_mode'] })}
                          className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
                        >
                          <option value="platform_first">Platform first</option>
                          <option value="organization_first">Organization first</option>
                          <option value="organization_only">Organization only</option>
                        </select>
                      </label>
                      <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                        Max LLM credentials
                        <input value={form.max_llm_credentials} onChange={e => setForm({ ...form, max_llm_credentials: e.target.value })} type="number" min="1" placeholder="3" className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                      </label>
                    </div>
                  </div>
                  <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
                    <input type="checkbox" checked={form.active} onChange={e => setForm({ ...form, active: e.target.checked })} />
                    Active
                  </label>
                  <button disabled={busy} className="w-full rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900">
                    Create Plan
                  </button>
                </div>
              </form>
            )}
          </section>

          <section className="rounded-lg border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            <div className="border-b border-zinc-200 px-5 py-3 font-semibold dark:border-zinc-800">Plan Catalog</div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1320px] text-left text-sm">
                <thead className="bg-zinc-50 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                  <tr>
                    <th className="px-4 py-3 font-medium">Plan</th>
                    <th className="px-4 py-3 font-medium">Price</th>
                    <th className="px-4 py-3 font-medium">Trial</th>
                    <th className="px-4 py-3 font-medium">Users</th>
                    <th className="px-4 py-3 font-medium">Campaigns</th>
                    <th className="px-4 py-3 font-medium">Leads</th>
                    <th className="px-4 py-3 font-medium">Emails</th>
                    <th className="px-4 py-3 font-medium">AI Credits</th>
                    <th className="px-4 py-3 font-medium">Routing</th>
                    <th className="px-4 py-3 font-medium">BYOK</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                  {sortedPlans.map(plan => (
                    <tr key={plan.id}>
                      <td className="px-4 py-3">
                        <div className="font-medium text-zinc-900 dark:text-zinc-100">{plan.name}</div>
                        <div className="text-xs text-zinc-500">{plan.slug}</div>
                        {plan.description && <div className="mt-1 max-w-xs text-xs text-zinc-500">{plan.description}</div>}
                      </td>
                      <td className="px-4 py-3">
                        <div>{formatMoney(plan.monthly_price_cents, plan.currency_code)}</div>
                        <div className="text-xs text-zinc-500">{plan.market_code}</div>
                      </td>
                      <td className="px-4 py-3">{plan.trial_days} days</td>
                      <td className="px-4 py-3">{formatLimit(plan.max_users)}</td>
                      <td className="px-4 py-3">{formatLimit(plan.max_campaigns)}</td>
                      <td className="px-4 py-3">{formatLimit(plan.max_leads)}</td>
                      <td className="px-4 py-3">{formatLimit(plan.max_monthly_emails)}</td>
                      <td className="px-4 py-3">
                        <div>{formatLimit(plan.max_monthly_ai_credits)}</div>
                        {plan.overage_allowed && (
                          <div className="text-xs text-zinc-500">{plan.overage_price_cents_per_ai_credit || 0}c overage</div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="text-xs text-zinc-500">Default</div>
                        <div>{plan.default_llm_routing_mode.replace('_', ' ')}</div>
                        <div className="mt-1 text-xs text-zinc-500">Paid: {formatRoutingModes(plan.allowed_llm_routing_modes)}</div>
                        <div className="text-xs text-zinc-500">Trial: {formatRoutingModes(plan.trial_allowed_llm_routing_modes)}</div>
                        {canManagePlans && (
                          <div className="mt-2 grid gap-2">
                            <select
                              value={plan.default_llm_routing_mode}
                              disabled={busy}
                              onChange={e => void updatePlanRouting(plan, { default_llm_routing_mode: e.target.value as SubscriptionPlan['default_llm_routing_mode'] })}
                              className="rounded-md border border-zinc-300 px-2 py-1 text-xs disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900"
                            >
                              {ROUTING_MODES.map(mode => <option key={mode} value={mode}>{mode.replace('_', ' ')}</option>)}
                            </select>
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div>{plan.allow_byok ? 'Allowed' : 'Not included'}</div>
                        {plan.allow_byok && (
                          <div className="text-xs text-zinc-500">
                            {plan.byok_provider_mode.replace('_', ' ')} · {formatLimit(plan.max_llm_credentials)}
                          </div>
                        )}
                        {canManagePlans && (
                          <div className="mt-2 grid gap-2">
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void updatePlanByok(plan, { allow_byok: !plan.allow_byok })}
                              className="rounded-md border border-zinc-300 px-2 py-1 text-xs disabled:opacity-50 dark:border-zinc-700"
                            >
                              {plan.allow_byok ? 'Disable BYOK' : 'Enable BYOK'}
                            </button>
                            <select
                              value={plan.byok_provider_mode}
                              disabled={busy || !plan.allow_byok}
                              onChange={e => void updatePlanByok(plan, { byok_provider_mode: e.target.value as SubscriptionPlan['byok_provider_mode'] })}
                              className="rounded-md border border-zinc-300 px-2 py-1 text-xs disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900"
                            >
                              <option value="platform_first">Platform first</option>
                              <option value="organization_first">Organization first</option>
                              <option value="organization_only">Organization only</option>
                            </select>
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">{plan.active ? 'Active' : 'Archived'}</td>
                      <td className="space-x-2 px-4 py-3">
                        <button
                          onClick={() => void choosePlan(plan)}
                          disabled={busy || !canChoosePlan || !plan.active || currentPlanId === plan.id}
                          className="rounded-md bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
                        >
                          {currentPlanId === plan.id ? 'Selected' : 'Choose'}
                        </button>
                        {canManagePlans && (
                          <button
                            onClick={() => void updatePlanActive(plan, !plan.active)}
                            disabled={busy}
                            className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium disabled:opacity-50 dark:border-zinc-700"
                          >
                            {plan.active ? 'Archive' : 'Activate'}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                  {sortedPlans.length === 0 && (
                    <tr>
                      <td colSpan={12} className="px-6 py-8 text-center text-zinc-500">No plans available.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      </main>
    </AppShell>
  )
}
