'use client'

import { useCallback, useEffect, useState } from 'react'
import { useAuth } from '@clerk/clerk-react'
import { AppShell } from '@/components/app-shell'
import { useTenantScope } from '@/components/tenant-scope'
import { fetchWithAuthRetry } from '@/lib/auth-fetch'
import { formatTimestamp } from '@/lib/time'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface UsageTotal {
  call_count: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  estimated_cost_usd: number
  fallback_count: number
  unpriced_count: number
  zero_cost_priced_count: number
  avg_latency_ms: number
}

interface UsageModelRow {
  provider: string
  model: string
  call_count: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  estimated_cost_usd: number
  unpriced_count: number
  zero_cost_priced_count: number
  pricing_sources: string | null
  avg_latency_ms: number
}

interface UsageEventRow {
  id: number
  request_id: string | null
  agent_name: string
  provider: string
  model: string
  routing_mode: string | null
  input_tokens: number
  output_tokens: number
  total_tokens: number
  latency_ms: number
  estimated_cost_usd: number
  pricing_source: string | null
  fallback_triggered: number | boolean
  attempt_count: number
  tool_call_count: number
  status: string
  created_at: string
}

interface UsagePayload {
  total: UsageTotal
  by_model: UsageModelRow[]
  recent: UsageEventRow[]
}

interface CustomerUsagePayload {
  ai: {
    action_count: number
    quantity: number
    credits_used: number
    included_credits: number | null
    remaining_credits: number | null
    overage_credits: number
  }
  by_action: Array<{
    action_type: string
    action_count: number
    quantity: number
    credits_used: number
  }>
  platform_by_event: Array<{
    event_type: string
    event_count: number
    quantity: number
  }>
  internal_cost: {
    estimated_cost_usd: number
    total_tokens: number
    call_count: number
  }
}

interface UnitEconomicsPayload {
  by_action: Array<{
    action_type: string
    action_count: number
    credits_used: number
    estimated_cost_usd: number
    total_tokens: number
    llm_calls: number
    avg_cost_per_action_usd: number
    avg_tokens_per_action: number
    avg_llm_calls_per_action: number
    cost_per_credit_usd: number
  }>
}

interface PlatformRuntimeSettings {
  llm_routing_mode: 'quality_first' | 'balanced' | 'cost_optimized'
  llm_routing_env_default: string
  allowed_llm_routing_modes: Array<'quality_first' | 'balanced' | 'cost_optimized'>
  organization_llm_keys_enabled: boolean
  organization_llm_provider_mode: string
}

function formatNumber(value: number) {
  return new Intl.NumberFormat('en-US').format(Math.round(value || 0))
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 5 }).format(value || 0)
}

function getErrorMessage(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback
}

function pricingSourceLabel(source: string | null | undefined) {
  if (!source) return 'Unknown'
  if (source === 'unpriced') return 'Unpriced'
  if (source === 'free-tier-or-external') return 'Configured Free'
  return source
}

function pricingBadgeClass(source: string | null | undefined, estimatedCost = 0) {
  if (source === 'unpriced') return 'bg-rose-100 text-rose-800 dark:bg-rose-950/40 dark:text-rose-300'
  if (estimatedCost === 0) return 'bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300'
  return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300'
}

export default function UsagePage() {
  const { isLoaded, userId, getToken } = useAuth()
  const { selectedOrganizationId, selectedOrganization, orgUrl } = useTenantScope()
  const [usage, setUsage] = useState<UsagePayload | null>(null)
  const [customerUsage, setCustomerUsage] = useState<CustomerUsagePayload | null>(null)
  const [unitEconomics, setUnitEconomics] = useState<UnitEconomicsPayload | null>(null)
  const [runtimeSettings, setRuntimeSettings] = useState<PlatformRuntimeSettings | null>(null)
  const [savingRoutingMode, setSavingRoutingMode] = useState(false)
  const [routingModeFilter, setRoutingModeFilter] = useState('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const authedFetch = useCallback((url: string, init: RequestInit = {}) => {
    return fetchWithAuthRetry(getToken, url, init)
  }, [getToken])

  const loadUsage = useCallback(async () => {
    try {
      setLoading(true)
      setError('')
      if (!selectedOrganizationId) return
      const usageUrl = new URL(orgUrl(`${API_BASE}/api/usage/llm`))
      usageUrl.searchParams.set('limit', '200')
      if (routingModeFilter !== 'all') {
        usageUrl.searchParams.set('routing_mode', routingModeFilter)
      }
      const res = await authedFetch(usageUrl.toString())
      if (!res.ok) throw new Error('Failed to load usage')
      setUsage(await res.json() as UsagePayload)
      const customerRes = await authedFetch(orgUrl(`${API_BASE}/api/usage/customer`))
      if (customerRes.ok) {
        setCustomerUsage(await customerRes.json() as CustomerUsagePayload)
      }
      const settingsRes = await authedFetch(`${API_BASE}/api/system/runtime-settings`)
      if (settingsRes.ok) {
        setRuntimeSettings(await settingsRes.json() as PlatformRuntimeSettings)
      } else {
        setRuntimeSettings(null)
      }
      if (selectedOrganization?.capabilities?.can_manage_subscription_plans) {
        const unitRes = await authedFetch(orgUrl(`${API_BASE}/api/usage/unit-economics`))
        if (unitRes.ok) {
          setUnitEconomics(await unitRes.json() as UnitEconomicsPayload)
        }
      } else {
        setUnitEconomics(null)
      }
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load usage'))
    } finally {
      setLoading(false)
    }
  }, [authedFetch, orgUrl, routingModeFilter, selectedOrganization, selectedOrganizationId])

  useEffect(() => {
    if (isLoaded && userId && selectedOrganizationId) {
      const timer = window.setTimeout(() => {
        void loadUsage()
      }, 0)
      return () => window.clearTimeout(timer)
    }
  }, [isLoaded, userId, selectedOrganizationId, loadUsage])

  const updateRoutingMode = async (mode: PlatformRuntimeSettings['llm_routing_mode']) => {
    try {
      setSavingRoutingMode(true)
      setError('')
      const res = await authedFetch(`${API_BASE}/api/system/llm-routing`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
      })
      if (!res.ok) throw new Error('Failed to update LLM routing mode')
      setRuntimeSettings(await res.json() as PlatformRuntimeSettings)
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to update LLM routing mode'))
    } finally {
      setSavingRoutingMode(false)
    }
  }

  if (!isLoaded || !userId) {
    return <div className="flex items-center justify-center min-h-screen">Loading or unauthorized...</div>
  }

  const total = usage?.total || {
    call_count: 0,
    input_tokens: 0,
    output_tokens: 0,
    total_tokens: 0,
    estimated_cost_usd: 0,
    fallback_count: 0,
    unpriced_count: 0,
    zero_cost_priced_count: 0,
    avg_latency_ms: 0,
  }

  return (
    <AppShell active="usage">
      <main className="flex-1 max-w-[92rem] mx-auto w-full p-8">
        <div className="flex flex-col justify-between gap-4 mb-6 md:flex-row md:items-center">
          <div>
            <h2 className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">LLM Usage</h2>
            <p className="text-sm text-zinc-500 mt-1">
              Token usage and estimated model cost from the local usage ledger.
            </p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <label className="text-sm text-zinc-600 dark:text-zinc-400">
              <span className="sr-only">Routing mode filter</span>
              <select
                value={routingModeFilter}
                onChange={(event) => setRoutingModeFilter(event.target.value)}
                className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
              >
                <option value="all">All routing modes</option>
                <option value="quality_first">Quality first</option>
                <option value="balanced">Balanced</option>
                <option value="cost_optimized">Cost optimized</option>
              </select>
            </label>
            <button
              onClick={() => void loadUsage()}
              className="px-3 py-2 border border-zinc-300 rounded-md text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              Refresh
            </button>
          </div>
        </div>

        {error && <div className="p-4 mb-4 text-red-700 bg-red-100 rounded-lg">{error}</div>}
        {total.unpriced_count > 0 && (
          <div className="p-4 mb-4 text-rose-800 bg-rose-100 rounded-lg dark:bg-rose-950/40 dark:text-rose-200">
            {formatNumber(total.unpriced_count)} call(s) have no pricing match. Add those provider/model prices to config/llm_pricing.json before using cost totals for billing.
          </div>
        )}

        {customerUsage && (
          <section className="mb-6 rounded-lg border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            <div className="mb-4 flex items-center justify-between gap-4">
              <div>
                <h3 className="font-semibold text-zinc-900 dark:text-zinc-100">Plan Usage</h3>
                <p className="text-sm text-zinc-500">Customer-facing AI credits and platform activity for this billing period.</p>
              </div>
              <div className="text-right text-sm">
                <div className="font-medium text-zinc-900 dark:text-zinc-100">
                  {formatNumber(customerUsage.ai.credits_used)} / {customerUsage.ai.included_credits === null ? 'Unlimited' : formatNumber(customerUsage.ai.included_credits)} credits
                </div>
                <div className="text-zinc-500">
                  {customerUsage.ai.remaining_credits === null ? 'No credit cap' : `${formatNumber(customerUsage.ai.remaining_credits)} remaining`}
                </div>
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <div className="rounded-md border border-zinc-200 p-4 dark:border-zinc-800">
                <div className="text-xs uppercase text-zinc-500">AI Actions</div>
                <div className="mt-2 text-xl font-semibold">{formatNumber(customerUsage.ai.action_count)}</div>
              </div>
              <div className="rounded-md border border-zinc-200 p-4 dark:border-zinc-800">
                <div className="text-xs uppercase text-zinc-500">Platform Events</div>
                <div className="mt-2 text-xl font-semibold">
                  {formatNumber(customerUsage.platform_by_event.reduce((sum, row) => sum + row.quantity, 0))}
                </div>
              </div>
              <div className="rounded-md border border-zinc-200 p-4 dark:border-zinc-800">
                <div className="text-xs uppercase text-zinc-500">Internal LLM Cost</div>
                <div className="mt-2 text-xl font-semibold">{formatCurrency(customerUsage.internal_cost.estimated_cost_usd)}</div>
              </div>
            </div>
          </section>
        )}

        {runtimeSettings && (
          <section className="mb-6 rounded-lg border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div>
                <h3 className="font-semibold text-zinc-900 dark:text-zinc-100">LLM Routing</h3>
                <p className="text-sm text-zinc-500">
                  Owner setting used by agent fallback before each LLM call unless a campaign override is set. Env default: {runtimeSettings.llm_routing_env_default}.
                </p>
              </div>
              <div className="inline-flex w-full rounded-md border border-zinc-300 p-1 text-sm dark:border-zinc-700 md:w-auto">
                {runtimeSettings.allowed_llm_routing_modes.map(mode => (
                  <button
                    key={mode}
                    type="button"
                    disabled={savingRoutingMode || runtimeSettings.llm_routing_mode === mode}
                    onClick={() => void updateRoutingMode(mode)}
                    aria-pressed={runtimeSettings.llm_routing_mode === mode}
                    title={
                      runtimeSettings.llm_routing_mode === mode
                        ? `${mode.replace('_', ' ')} is active`
                        : `Switch future platform-default LLM calls to ${mode.replace('_', ' ')}`
                    }
                    className={`flex-1 rounded px-3 py-2 font-medium capitalize md:flex-none ${
                      runtimeSettings.llm_routing_mode === mode
                        ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900'
                        : 'cursor-pointer text-zinc-700 hover:bg-zinc-100 disabled:opacity-60 dark:text-zinc-200 dark:hover:bg-zinc-800'
                    }`}
                  >
                    {mode.replace('_', ' ')}
                  </button>
                ))}
              </div>
            </div>
            <div className="grid gap-3 text-sm md:grid-cols-3">
              <div className="rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
                <div className="font-medium">Quality First</div>
                <div className="mt-1 text-zinc-500">Azure/OpenAI-first routing for maximum reliability.</div>
              </div>
              <div className="rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
                <div className="font-medium">Balanced</div>
                <div className="mt-1 text-zinc-500">Recommended: cheaper capable models for simple work, strong models for safety/tools.</div>
              </div>
              <div className="rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
                <div className="font-medium">Cost Optimized</div>
                <div className="mt-1 text-zinc-500">Aggressive cost saving for high-volume lower-risk workflows.</div>
              </div>
            </div>
          </section>
        )}

        {unitEconomics && unitEconomics.by_action.length > 0 && (
          <section className="mb-6 overflow-hidden rounded-lg border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            <div className="border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
              <h3 className="font-semibold text-zinc-900 dark:text-zinc-100">Unit Economics</h3>
              <p className="text-sm text-zinc-500">Owner view: average LLM cost and token load by product action.</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[920px] text-left text-sm">
                <thead className="bg-zinc-50 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                  <tr>
                    <th className="px-4 py-3 font-medium">Action</th>
                    <th className="px-4 py-3 font-medium">Count</th>
                    <th className="px-4 py-3 font-medium">Credits</th>
                    <th className="px-4 py-3 font-medium">Avg Cost</th>
                    <th className="px-4 py-3 font-medium">Cost / Credit</th>
                    <th className="px-4 py-3 font-medium">Avg Tokens</th>
                    <th className="px-4 py-3 font-medium">Avg Calls</th>
                    <th className="px-4 py-3 font-medium">Total Cost</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                  {unitEconomics.by_action.map(row => (
                    <tr key={row.action_type}>
                      <td className="px-4 py-3 font-medium">{row.action_type}</td>
                      <td className="px-4 py-3">{formatNumber(row.action_count)}</td>
                      <td className="px-4 py-3">{formatNumber(row.credits_used)}</td>
                      <td className="px-4 py-3">{formatCurrency(row.avg_cost_per_action_usd)}</td>
                      <td className="px-4 py-3">{formatCurrency(row.cost_per_credit_usd)}</td>
                      <td className="px-4 py-3">{formatNumber(row.avg_tokens_per_action)}</td>
                      <td className="px-4 py-3">{row.avg_llm_calls_per_action.toFixed(2)}</td>
                      <td className="px-4 py-3">{formatCurrency(row.estimated_cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        <section className="grid grid-cols-2 lg:grid-cols-8 gap-4 mb-6">
          {[
            ['Calls', formatNumber(total.call_count)],
            ['Input Tokens', formatNumber(total.input_tokens)],
            ['Output Tokens', formatNumber(total.output_tokens)],
            ['Total Tokens', formatNumber(total.total_tokens)],
            ['Est. Cost', formatCurrency(total.estimated_cost_usd)],
            ['Fallbacks', formatNumber(total.fallback_count)],
            ['Unpriced', formatNumber(total.unpriced_count)],
            ['Zero Cost', formatNumber(total.zero_cost_priced_count)],
          ].map(([label, value]) => (
            <div key={label} className="bg-white border border-zinc-200 rounded-lg p-4 dark:bg-zinc-900 dark:border-zinc-800">
              <div className="text-xs uppercase tracking-wide text-zinc-500">{label}</div>
              <div className="mt-2 text-xl font-semibold text-zinc-900 dark:text-zinc-100">{value}</div>
            </div>
          ))}
        </section>

        <section className="bg-white border border-zinc-200 rounded-lg shadow-sm dark:bg-zinc-900 dark:border-zinc-800 overflow-hidden mb-6">
          <div className="px-4 py-3 border-b border-zinc-200 dark:border-zinc-800 font-semibold">Usage By Model</div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm min-w-[820px]">
              <thead className="bg-zinc-50 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400">
                <tr>
                  <th className="px-4 py-3 font-medium">Provider</th>
                  <th className="px-4 py-3 font-medium">Model</th>
                  <th className="px-4 py-3 font-medium">Calls</th>
                  <th className="px-4 py-3 font-medium">Tokens</th>
                  <th className="px-4 py-3 font-medium">Pricing</th>
                  <th className="px-4 py-3 font-medium">Avg Latency</th>
                  <th className="px-4 py-3 font-medium">Est. Cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                {(usage?.by_model || []).map((row) => (
                  <tr key={`${row.provider}:${row.model}`}>
                    <td className="px-4 py-3">{row.provider}</td>
                    <td className="px-4 py-3">{row.model}</td>
                    <td className="px-4 py-3">{formatNumber(row.call_count)}</td>
                    <td className="px-4 py-3">{formatNumber(row.total_tokens)}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex rounded-md px-2 py-1 text-xs font-medium ${pricingBadgeClass(row.unpriced_count > 0 ? 'unpriced' : row.pricing_sources, row.estimated_cost_usd)}`}>
                        {row.unpriced_count > 0 ? `${formatNumber(row.unpriced_count)} unpriced` : pricingSourceLabel(row.pricing_sources)}
                      </span>
                    </td>
                    <td className="px-4 py-3">{formatNumber(row.avg_latency_ms)} ms</td>
                    <td className="px-4 py-3">{formatCurrency(row.estimated_cost_usd)}</td>
                  </tr>
                ))}
                {!loading && (usage?.by_model || []).length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-6 py-8 text-center text-zinc-500">No usage events recorded yet.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="bg-white border border-zinc-200 rounded-lg shadow-sm dark:bg-zinc-900 dark:border-zinc-800 overflow-hidden">
          <div className="px-4 py-3 border-b border-zinc-200 dark:border-zinc-800 font-semibold">Recent Calls</div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm min-w-[1220px]">
              <thead className="bg-zinc-50 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400">
                <tr>
                  <th className="px-4 py-3 font-medium">Time</th>
                  <th className="px-4 py-3 font-medium">Agent</th>
                  <th className="px-4 py-3 font-medium">Routing</th>
                  <th className="px-4 py-3 font-medium">Model</th>
                  <th className="px-4 py-3 font-medium">Input</th>
                  <th className="px-4 py-3 font-medium">Output</th>
                  <th className="px-4 py-3 font-medium">Total</th>
                  <th className="px-4 py-3 font-medium">Latency</th>
                  <th className="px-4 py-3 font-medium">Cost</th>
                  <th className="px-4 py-3 font-medium">Pricing</th>
                  <th className="px-4 py-3 font-medium">Fallback</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                {(usage?.recent || []).map((row) => (
                  <tr key={row.id}>
                    <td className="px-4 py-3 text-zinc-500">{formatTimestamp(row.created_at, selectedOrganization?.timezone)}</td>
                    <td className="px-4 py-3">{row.agent_name}</td>
                    <td className="px-4 py-3">
                      {row.routing_mode ? (
                        <span className="inline-flex rounded-md bg-zinc-100 px-2 py-1 text-xs font-medium capitalize text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200">
                          {row.routing_mode.replace('_', ' ')}
                        </span>
                      ) : (
                        <span className="text-zinc-400">Legacy</span>
                      )}
                    </td>
                    <td className="px-4 py-3">{row.provider} / {row.model}</td>
                    <td className="px-4 py-3">{formatNumber(row.input_tokens)}</td>
                    <td className="px-4 py-3">{formatNumber(row.output_tokens)}</td>
                    <td className="px-4 py-3">{formatNumber(row.total_tokens)}</td>
                    <td className="px-4 py-3">{formatNumber(row.latency_ms)} ms</td>
                    <td className="px-4 py-3">{formatCurrency(row.estimated_cost_usd)}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex rounded-md px-2 py-1 text-xs font-medium ${pricingBadgeClass(row.pricing_source, row.estimated_cost_usd)}`}>
                        {pricingSourceLabel(row.pricing_source)}
                      </span>
                    </td>
                    <td className="px-4 py-3">{row.fallback_triggered ? `Yes (${row.attempt_count})` : 'No'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </AppShell>
  )
}
