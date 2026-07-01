'use client'

import { useAuth } from '@clerk/clerk-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { AppShell } from '@/components/app-shell'
import { useTenantScope } from '@/components/tenant-scope'
import { fetchWithAuthRetry } from '@/lib/auth-fetch'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

type Provider = 'openai' | 'azure_openai' | 'gemini' | 'groq' | 'cerebras' | 'openrouter'

interface Credential {
  id: number
  provider: Provider
  label: string
  status: 'ACTIVE' | 'DISABLED'
  default_model: string | null
  base_url: string | null
  azure_endpoint: string | null
  azure_deployment: string | null
  azure_api_version: string | null
  last_used_at: string | null
  last_tested_at: string | null
  last_error: string | null
  updated_at: string | null
  api_key_fingerprint?: { present: boolean; len?: number; sha12?: string | null }
}

interface Policy {
  enabled: boolean
  global_enabled: boolean
  plan_allows_byok: boolean
  provider_mode: 'platform_first' | 'organization_first' | 'organization_only'
  max_credentials: number | null
  supported_providers: Provider[]
  security_note: string
}

interface FormState {
  provider: Provider
  label: string
  api_key: string
  default_model: string
  base_url: string
  azure_endpoint: string
  azure_deployment: string
  azure_api_version: string
}

const providerCopy: Record<Provider, { label: string; keyName: string; modelHint: string }> = {
  openai: { label: 'OpenAI', keyName: 'OPENAI_API_KEY', modelHint: 'gpt-4o-mini, gpt-4.1-mini, or your preferred OpenAI model' },
  azure_openai: { label: 'Azure OpenAI', keyName: 'AZURE_OPENAI_API_KEY', modelHint: 'Use your Azure deployment name' },
  gemini: { label: 'Google Gemini', keyName: 'GEMINI_API_KEY', modelHint: 'gemini-2.5-flash' },
  groq: { label: 'Groq', keyName: 'GROQ_API_KEY', modelHint: 'llama-3.3-70b-versatile' },
  cerebras: { label: 'Cerebras', keyName: 'CEREBRAS_API_KEY', modelHint: 'gpt-oss-120b' },
  openrouter: { label: 'OpenRouter', keyName: 'OPENROUTER_API_KEY', modelHint: 'openrouter/auto, anthropic/claude-sonnet-4.6, or a specific routed model' },
}

const byokModelGuide = [
  {
    workflow: 'Outbound drafts and inbound replies',
    bestFit: 'Creative, user-facing writing with structured JSON output.',
    recommended: 'gpt-4.1-mini, gpt-4o-mini, gemini-2.5-flash, anthropic/claude-sonnet-4.6 via OpenRouter',
    caution: 'Free or router-auto models can work, but should be tested before production campaigns.',
  },
  {
    workflow: 'Review, approval, and classification',
    bestFit: 'Conservative structured decisions where JSON/schema reliability matters.',
    recommended: 'gpt-4.1-mini, gpt-4o-mini, gemini-2.5-flash, gpt-oss-120b',
    caution: 'Models without reliable structured output may be skipped by the platform.',
  },
  {
    workflow: 'Safety checks and sender/tool actions',
    bestFit: 'Strict behavior, safety classification, and tool-calling reliability.',
    recommended: 'Azure/OpenAI deployments or validated OpenAI-compatible models',
    caution: 'These workflows may ignore or skip BYOK models that do not support required safety or tool capabilities.',
  },
] as const

function emptyForm(): FormState {
  return {
    provider: 'openai',
    label: '',
    api_key: '',
    default_model: '',
    base_url: '',
    azure_endpoint: '',
    azure_deployment: '',
    azure_api_version: '',
  }
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

function formatTimestamp(value: string | null) {
  if (!value) return 'Never'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

export default function LLMCredentialsPage() {
  const { isLoaded, userId, getToken } = useAuth()
  const { loading, selectedOrganizationId, selectedOrganization } = useTenantScope()
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [policy, setPolicy] = useState<Policy | null>(null)
  const [form, setForm] = useState<FormState>(() => emptyForm())
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const selectedProvider = providerCopy[form.provider]
  const canManage = !!selectedOrganization?.capabilities?.can_manage_llm_credentials
  const credentialLimitReached = policy?.max_credentials != null && credentials.length >= policy.max_credentials

  const authedFetch = useCallback(async (url: string, init: RequestInit = {}) => {
    return fetchWithAuthRetry(getToken, url, init)
  }, [getToken])

  const loadCredentials = useCallback(async () => {
    if (!isLoaded || !userId || !selectedOrganizationId) return
    setError('')
    try {
      const res = await authedFetch(`${API_BASE}/api/organizations/${selectedOrganizationId}/llm-credentials`)
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Failed to load LLM credentials')
      setCredentials(data.credentials || [])
      setPolicy(data.policy || null)
    } catch (err) {
      setError(errorMessage(err, 'Failed to load LLM credentials'))
    }
  }, [authedFetch, isLoaded, selectedOrganizationId, userId])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadCredentials()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadCredentials])

  const testCredential = useCallback(async (credential: Credential) => {
    if (!selectedOrganizationId || !canManage) return { ok: false, message: 'Testing is not available.' }
    const res = await authedFetch(`${API_BASE}/api/organizations/${selectedOrganizationId}/llm-credentials/${credential.id}/test`, {
      method: 'POST',
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || 'Failed to test credential')
    if (data.credential) {
      setCredentials(items => items.map(item => item.id === credential.id ? data.credential : item))
    }
    return { ok: data.status === 'passed', message: data.message || 'Credential test completed.' }
  }, [authedFetch, canManage, selectedOrganizationId])

  const createCredential = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedOrganizationId || !canManage || !policy?.enabled || credentialLimitReached) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const payload = {
        provider: form.provider,
        label: form.label || null,
        api_key: form.api_key,
        default_model: form.default_model || null,
        base_url: form.base_url || null,
        azure_endpoint: form.azure_endpoint || null,
        azure_deployment: form.azure_deployment || null,
        azure_api_version: form.azure_api_version || null,
      }
      const res = await authedFetch(`${API_BASE}/api/organizations/${selectedOrganizationId}/llm-credentials`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Failed to store credential')
      setCredentials(items => [...items, data.credential])
      const testResult = await testCredential(data.credential)
      setForm(emptyForm())
      setShowAdvanced(false)
      if (testResult.ok) {
        setNotice('Credential saved and test passed. The key value will not be shown again.')
      } else {
        setNotice('Credential saved. The key value will not be shown again.')
        setError(testResult.message)
      }
    } catch (err) {
      setError(errorMessage(err, 'Failed to store credential'))
    } finally {
      setBusy(false)
    }
  }

  const updateStatus = async (credential: Credential, status: Credential['status']) => {
    if (!selectedOrganizationId || !canManage) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const res = await authedFetch(`${API_BASE}/api/organizations/${selectedOrganizationId}/llm-credentials/${credential.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Failed to update credential')
      setCredentials(items => items.map(item => item.id === credential.id ? data.credential : item))
      setNotice(status === 'ACTIVE' ? 'Credential enabled.' : 'Credential disabled.')
    } catch (err) {
      setError(errorMessage(err, 'Failed to update credential'))
    } finally {
      setBusy(false)
    }
  }

  const deleteCredential = async (credential: Credential) => {
    if (!selectedOrganizationId || !canManage) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const res = await authedFetch(`${API_BASE}/api/organizations/${selectedOrganizationId}/llm-credentials/${credential.id}`, {
        method: 'DELETE',
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Failed to delete credential')
      setCredentials(items => items.filter(item => item.id !== credential.id))
      setNotice('Credential deleted.')
    } catch (err) {
      setError(errorMessage(err, 'Failed to delete credential'))
    } finally {
      setBusy(false)
    }
  }

  const runCredentialTest = async (credential: Credential) => {
    if (!selectedOrganizationId || !canManage) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const result = await testCredential(credential)
      if (result.ok) {
        setNotice(result.message)
      } else {
        setError(result.message)
      }
    } catch (err) {
      setError(errorMessage(err, 'Failed to test credential'))
    } finally {
      setBusy(false)
    }
  }

  const providerRows = useMemo(() => Object.entries(providerCopy) as Array<[Provider, typeof providerCopy[Provider]]>, [])

  if (!isLoaded || !userId || loading) {
    return <div className="flex min-h-screen items-center justify-center">Loading or unauthorized...</div>
  }

  return (
    <AppShell active="llm-credentials">
      <main className="mx-auto w-full max-w-[88rem] p-6 lg:p-8">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">LLM Keys</h1>
          <p className="mt-1 text-sm text-zinc-500">
            {selectedOrganization?.name || 'Selected organization'} · {policy?.provider_mode?.replace('_', ' ') || 'platform first'}
          </p>
        </div>

        {error && <div className="mb-4 rounded-md bg-rose-100 p-4 text-sm text-rose-700">{error}</div>}
        {notice && <div className="mb-4 rounded-md bg-emerald-100 p-4 text-sm text-emerald-800">{notice}</div>}

        <div className="mb-6 rounded-lg border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="text-base font-semibold">Credential privacy</h2>
          <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">
            {policy?.security_note || 'Provider keys are encrypted before storage and are never shown again. Only provider metadata and a short fingerprint are visible to admins.'}
          </p>
          <div className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
            <div className="rounded-md bg-zinc-50 p-3 dark:bg-zinc-800">
              <div className="text-zinc-500">Plan access</div>
              <div className="font-medium">{policy?.plan_allows_byok ? 'BYOK included' : 'Not included in current plan'}</div>
            </div>
            <div className="rounded-md bg-zinc-50 p-3 dark:bg-zinc-800">
              <div className="text-zinc-500">Deployment switch</div>
              <div className="font-medium">{policy?.global_enabled ? 'Enabled' : 'Disabled'}</div>
            </div>
            <div className="rounded-md bg-zinc-50 p-3 dark:bg-zinc-800">
              <div className="text-zinc-500">Credential limit</div>
              <div className="font-medium">{policy?.max_credentials ?? 'Unlimited'}</div>
            </div>
          </div>
        </div>

        <section className="mb-6 rounded-lg border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <div className="border-b border-zinc-200 px-5 py-3 dark:border-zinc-800">
            <h2 className="text-base font-semibold">BYOK model guide</h2>
            <p className="mt-1 text-sm text-zinc-500">
              For most tenants, pick a provider and model for drafting/replies. The platform will keep stricter review, safety, and sending workflows on compatible models when needed.
            </p>
          </div>
          <div className="border-b border-zinc-200 px-5 py-4 text-sm text-zinc-600 dark:border-zinc-800 dark:text-zinc-300">
            If you use a premium model like Claude through OpenRouter for copywriting, keep at least one structured-output model available for review/classification, such as
            {' '}<span className="font-medium text-zinc-900 dark:text-zinc-100">gpt-4o-mini</span>,
            {' '}<span className="font-medium text-zinc-900 dark:text-zinc-100">gpt-4.1-mini</span>,
            {' '}<span className="font-medium text-zinc-900 dark:text-zinc-100">gemini-2.5-flash</span>, or
            {' '}<span className="font-medium text-zinc-900 dark:text-zinc-100">gpt-oss-120b</span>.
          </div>
          <div className="grid gap-3 p-5 lg:grid-cols-3">
            {byokModelGuide.map(item => (
              <div key={item.workflow} className="rounded-md border border-zinc-200 p-4 dark:border-zinc-800">
                <h3 className="font-medium text-zinc-900 dark:text-zinc-100">{item.workflow}</h3>
                <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">{item.bestFit}</p>
                <div className="mt-4">
                  <div className="text-xs font-medium uppercase tracking-wide text-zinc-500">Recommended model names</div>
                  <p className="mt-1 text-sm text-zinc-700 dark:text-zinc-300">{item.recommended}</p>
                </div>
                <p className="mt-3 text-xs leading-5 text-zinc-500">{item.caution}</p>
              </div>
            ))}
          </div>
        </section>

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[390px_minmax(0,1fr)]">
          <form onSubmit={createCredential} className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="text-base font-semibold">Add provider key</h2>
            {!policy?.enabled && (
              <div className="mt-4 rounded-md bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-900/30 dark:text-amber-100">
                BYOK is not active for this organization. Enable it on the plan and set ORGANIZATION_LLM_KEYS_ENABLED=true for the deployment.
              </div>
            )}
            <div className="mt-4 space-y-3">
              <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                Provider
                <select
                  value={form.provider}
                  onChange={e => {
                    setForm({ ...form, provider: e.target.value as Provider })
                    setShowAdvanced(false)
                  }}
                  className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
                >
                  {providerRows.map(([key, provider]) => (
                    <option key={key} value={key}>{provider.label}</option>
                  ))}
                </select>
              </label>
              <p className="rounded-md bg-zinc-50 px-3 py-2 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                {form.provider === 'azure_openai'
                  ? 'Required: API key, Azure endpoint, and deployment. Everything else can use platform defaults.'
                  : 'Required: API key only. Model, base URL, and label can use platform defaults.'}
              </p>
              <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                {selectedProvider.keyName}
                <input value={form.api_key} onChange={e => setForm({ ...form, api_key: e.target.value })} required type="password" autoComplete="off" placeholder="Paste key value" className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
              </label>
              {form.provider === 'azure_openai' && (
                <div className="grid gap-3">
                  <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                    Azure endpoint
                    <input value={form.azure_endpoint} onChange={e => setForm({ ...form, azure_endpoint: e.target.value })} required placeholder="https://resource.openai.azure.com" className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                  </label>
                  <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                    Deployment
                    <input value={form.azure_deployment} onChange={e => setForm({ ...form, azure_deployment: e.target.value })} required placeholder="gpt-4o-mini" className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                  </label>
                </div>
              )}
              <button
                type="button"
                onClick={() => setShowAdvanced(value => !value)}
                className="w-full rounded-md border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-700 dark:border-zinc-700 dark:text-zinc-200"
              >
                {showAdvanced ? 'Hide advanced options' : 'Show advanced options'}
              </button>
              {showAdvanced && (
                <div className="space-y-3 rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
                  <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                    Label
                    <input value={form.label} onChange={e => setForm({ ...form, label: e.target.value })} placeholder={`${selectedProvider.label} primary`} className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                  </label>
                  <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                    Default model
                    <input value={form.default_model} onChange={e => setForm({ ...form, default_model: e.target.value })} placeholder={selectedProvider.modelHint} className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                  </label>
                  {form.provider !== 'azure_openai' && (
                    <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                      Base URL
                      <input value={form.base_url} onChange={e => setForm({ ...form, base_url: e.target.value })} placeholder="Optional provider-compatible endpoint" className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                    </label>
                  )}
                  {form.provider === 'azure_openai' && (
                    <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                      API version
                      <input value={form.azure_api_version} onChange={e => setForm({ ...form, azure_api_version: e.target.value })} placeholder="Uses platform default if left blank" className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                    </label>
                  )}
                </div>
              )}
              <button disabled={busy || !canManage || !policy?.enabled || credentialLimitReached} className="w-full rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900">
                Save encrypted key
              </button>
            </div>
          </form>

          <section className="rounded-lg border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            <div className="border-b border-zinc-200 px-5 py-3 font-semibold dark:border-zinc-800">Stored Credentials</div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-left text-sm">
                <thead className="bg-zinc-50 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                  <tr>
                    <th className="px-4 py-3 font-medium">Provider</th>
                    <th className="px-4 py-3 font-medium">Model</th>
                    <th className="px-4 py-3 font-medium">Fingerprint</th>
                    <th className="px-4 py-3 font-medium">Health</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                  {credentials.map(credential => (
                    <tr key={credential.id}>
                      <td className="px-4 py-3">
                        <div className="font-medium">{credential.label}</div>
                        <div className="text-xs text-zinc-500">{providerCopy[credential.provider]?.label || credential.provider}</div>
                      </td>
                      <td className="px-4 py-3">{credential.default_model || 'Provider default'}</td>
                      <td className="px-4 py-3 font-mono text-xs">{credential.api_key_fingerprint?.sha12 || 'unavailable'}</td>
                      <td className="px-4 py-3">
                        <div className={credential.last_error ? 'text-rose-700 dark:text-rose-300' : 'text-zinc-700 dark:text-zinc-200'}>
                          {credential.last_tested_at ? (credential.last_error ? 'Failed' : 'Passed') : 'Not tested'}
                        </div>
                        <div className="text-xs text-zinc-500">{formatTimestamp(credential.last_tested_at)}</div>
                        {credential.last_error && <div className="mt-1 max-w-xs text-xs text-rose-700 dark:text-rose-300">{credential.last_error}</div>}
                      </td>
                      <td className="px-4 py-3">{credential.status}</td>
                      <td className="space-x-2 px-4 py-3">
                        <button disabled={busy || !canManage} onClick={() => void runCredentialTest(credential)} className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium disabled:opacity-50 dark:border-zinc-700">
                          Test
                        </button>
                        <button disabled={busy || !canManage} onClick={() => void updateStatus(credential, credential.status === 'ACTIVE' ? 'DISABLED' : 'ACTIVE')} className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium disabled:opacity-50 dark:border-zinc-700">
                          {credential.status === 'ACTIVE' ? 'Disable' : 'Enable'}
                        </button>
                        <button disabled={busy || !canManage} onClick={() => void deleteCredential(credential)} className="rounded-md border border-rose-300 px-3 py-1.5 text-xs font-medium text-rose-700 disabled:opacity-50 dark:border-rose-800 dark:text-rose-300">
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                  {credentials.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-6 py-8 text-center text-zinc-500">No organization LLM keys have been stored.</td>
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
