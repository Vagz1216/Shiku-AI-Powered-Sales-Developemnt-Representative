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
  trial_days: string
  max_users: string
  max_campaigns: string
  max_leads: string
  max_monthly_emails: string
  max_monthly_ai_tokens: string
  max_monthly_ai_credits: string
  overage_allowed: boolean
  overage_price_cents_per_ai_credit: string
  active: boolean
}

function emptyPlanForm(): PlanFormState {
  return {
    name: '',
    slug: '',
    description: '',
    monthly_price: '0',
    trial_days: '14',
    max_users: '',
    max_campaigns: '',
    max_leads: '',
    max_monthly_emails: '',
    max_monthly_ai_tokens: '',
    max_monthly_ai_credits: '',
    overage_allowed: false,
    overage_price_cents_per_ai_credit: '',
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

function formatMoney(cents: number) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format((cents || 0) / 100)
}

function formatLimit(value: number | null) {
  return value ? new Intl.NumberFormat('en-US').format(value) : 'Unlimited'
}

function getErrorMessage(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback
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
          trial_days: Number(form.trial_days || 0),
          max_users: optionalNumber(form.max_users),
          max_campaigns: optionalNumber(form.max_campaigns),
          max_leads: optionalNumber(form.max_leads),
          max_monthly_emails: optionalNumber(form.max_monthly_emails),
          max_monthly_ai_tokens: optionalNumber(form.max_monthly_ai_tokens),
          max_monthly_ai_credits: optionalNumber(form.max_monthly_ai_credits),
          overage_allowed: form.overage_allowed,
          overage_price_cents_per_ai_credit: optionalNumber(form.overage_price_cents_per_ai_credit),
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
                      Monthly price (USD)
                      <input value={form.monthly_price} onChange={e => setForm({ ...form, monthly_price: e.target.value })} type="number" min="0" step="1" placeholder="49" className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                    </label>
                    <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                      Trial days
                      <input value={form.trial_days} onChange={e => setForm({ ...form, trial_days: e.target.value })} type="number" min="0" placeholder="14" className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
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
              <table className="w-full min-w-[1120px] text-left text-sm">
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
                      <td className="px-4 py-3">{formatMoney(plan.monthly_price_cents)}</td>
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
                      <td colSpan={10} className="px-6 py-8 text-center text-zinc-500">No plans available.</td>
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
