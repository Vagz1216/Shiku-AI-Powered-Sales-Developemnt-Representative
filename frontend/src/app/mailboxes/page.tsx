'use client'

import { useCallback, useEffect, useState } from 'react'
import { useAuth } from '@clerk/clerk-react'
import { ActionFeedback, type ActionFeedbackState } from '@/components/action-feedback'
import { AppShell } from '@/components/app-shell'
import { useTenantScope } from '@/components/tenant-scope'
import { formatTimestamp } from '@/lib/time'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Mailbox {
  id: number
  organization_id: number
  provider: string
  display_name: string | null
  email_address: string
  status: string
  smtp_host: string | null
  smtp_port: number | null
  smtp_use_ssl: number | boolean
  smtp_username: string | null
  imap_host: string | null
  imap_port: number | null
  imap_use_ssl: number | boolean
  imap_username: string | null
  resend_domain: string | null
  resend_from_email: string | null
  resend_reply_to: string | null
  daily_limit: number
  last_tested_at: string | null
  last_error: string | null
  has_smtp_password: boolean
  has_imap_password: boolean
  has_resend_api_key: boolean
  has_resend_webhook_secret: boolean
}

interface MailboxForm {
  provider: 'smtp_imap' | 'resend'
  display_name: string
  email_address: string
  smtp_host: string
  smtp_port: string
  smtp_use_ssl: boolean
  smtp_username: string
  smtp_password: string
  imap_host: string
  imap_port: string
  imap_use_ssl: boolean
  imap_username: string
  imap_password: string
  resend_domain: string
  resend_from_email: string
  resend_reply_to: string
  resend_api_key: string
  resend_webhook_secret: string
  daily_limit: string
}

interface MailboxSyncResponse {
  checked?: number
  processed?: unknown[]
  skipped?: unknown[]
  errors?: unknown[]
}

const emptyForm: MailboxForm = {
  provider: 'smtp_imap',
  display_name: 'Market Hacks',
  email_address: 'info@markethacks.co.ke',
  smtp_host: 'mail.markethacks.co.ke',
  smtp_port: '465',
  smtp_use_ssl: true,
  smtp_username: 'info@markethacks.co.ke',
  smtp_password: '',
  imap_host: 'mail.markethacks.co.ke',
  imap_port: '993',
  imap_use_ssl: true,
  imap_username: 'info@markethacks.co.ke',
  imap_password: '',
  resend_domain: 'outreach.markethacks.co.ke',
  resend_from_email: 'Market Hacks <info@markethacks.co.ke>',
  resend_reply_to: 'info@markethacks.co.ke',
  resend_api_key: '',
  resend_webhook_secret: '',
  daily_limit: '100',
}

function getErrorMessage(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback
}

function mailboxSyncFeedback(data: MailboxSyncResponse): NonNullable<ActionFeedbackState> {
  const checked = data.checked || 0
  const processed = (data.processed || []).length
  const skipped = (data.skipped || []).length
  const errors = (data.errors || []).length
  const summary = `Checked ${checked} unread message(s), processed ${processed}, skipped ${skipped}.`

  if (errors > 0) {
    return {
      type: 'warning',
      message: `Mailbox sync completed with ${errors} message error(s). ${summary}`,
    }
  }

  return {
    type: 'success',
    message: `Mailbox sync complete. ${summary}`,
  }
}

export default function MailboxesPage() {
  const { isLoaded, userId, getToken } = useAuth()
  const { loading: orgLoading, selectedOrganizationId, selectedOrganization } = useTenantScope()
  const [mailboxes, setMailboxes] = useState<Mailbox[]>([])
  const [form, setForm] = useState<MailboxForm>(emptyForm)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testingId, setTestingId] = useState<number | null>(null)
  const [syncingId, setSyncingId] = useState<number | null>(null)
  const [feedback, setFeedback] = useState<ActionFeedbackState>(null)
  const [syncResults, setSyncResults] = useState<Record<number, ActionFeedbackState>>({})
  const canManageMailboxes = !!selectedOrganization?.capabilities?.can_manage_mailboxes
  const canSyncMailboxes = canManageMailboxes || selectedOrganization?.current_user_role === 'sales_manager'

  const authedFetch = useCallback(async (url: string, init: RequestInit = {}) => {
    const token = await getToken()
    const headers = new Headers(init.headers)
    headers.set('Authorization', `Bearer ${token}`)
    return fetch(url, { ...init, headers })
  }, [getToken])

  const loadMailboxes = useCallback(async (organizationId: number) => {
    if (!organizationId) return
    setLoading(true)
    try {
      const res = await authedFetch(`${API_BASE}/api/organizations/${organizationId}/mailboxes`)
      if (!res.ok) throw new Error(await responseText(res, 'Failed to load mailboxes'))
      const data = await res.json() as { mailboxes: Mailbox[] }
      setMailboxes(data.mailboxes || [])
    } catch (err: unknown) {
      setFeedback({ type: 'error', message: getErrorMessage(err, 'Failed to load mailboxes') })
      setMailboxes([])
    } finally {
      setLoading(false)
    }
  }, [authedFetch])

  useEffect(() => {
    if (isLoaded && userId && selectedOrganizationId) {
      const timer = window.setTimeout(() => {
        void loadMailboxes(selectedOrganizationId)
      }, 0)
      return () => window.clearTimeout(timer)
    }
  }, [isLoaded, userId, selectedOrganizationId, loadMailboxes])

  useEffect(() => {
    if (isLoaded && userId && !orgLoading && !selectedOrganizationId) {
      const timer = window.setTimeout(() => {
        setMailboxes([])
        setLoading(false)
      }, 0)
      return () => window.clearTimeout(timer)
    }
  }, [isLoaded, orgLoading, selectedOrganizationId, userId])

  const updateForm = (field: keyof MailboxForm, value: string | boolean) => {
    setForm((current) => ({ ...current, [field]: value }))
  }

  const submitMailbox = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedOrganizationId || !canManageMailboxes) return
    setSaving(true)
    setFeedback(null)
    try {
      const payload = {
        provider: form.provider,
        display_name: form.display_name,
        email_address: form.email_address,
        smtp_host: form.provider === 'smtp_imap' ? form.smtp_host : null,
        smtp_port: form.provider === 'smtp_imap' ? Number(form.smtp_port) : null,
        smtp_use_ssl: form.smtp_use_ssl,
        smtp_username: form.provider === 'smtp_imap' ? form.smtp_username : null,
        smtp_password: form.provider === 'smtp_imap' ? form.smtp_password : null,
        imap_host: form.provider === 'smtp_imap' ? form.imap_host : null,
        imap_port: form.provider === 'smtp_imap' ? Number(form.imap_port) : null,
        imap_use_ssl: form.imap_use_ssl,
        imap_username: form.provider === 'smtp_imap' ? form.imap_username : null,
        imap_password: form.provider === 'smtp_imap' ? form.imap_password : null,
        resend_domain: form.provider === 'resend' ? form.resend_domain || null : null,
        resend_from_email: form.provider === 'resend' ? form.resend_from_email : null,
        resend_reply_to: form.provider === 'resend' ? form.resend_reply_to || null : null,
        resend_api_key: form.provider === 'resend' ? form.resend_api_key : null,
        resend_webhook_secret: form.provider === 'resend' ? form.resend_webhook_secret || null : null,
        daily_limit: Number(form.daily_limit),
      }
      const res = await authedFetch(`${API_BASE}/api/organizations/${selectedOrganizationId}/mailboxes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error(await responseText(res, 'Failed to save mailbox'))
      const data = await res.json() as { mailbox: Mailbox }
      setFeedback({ type: 'success', message: `Saved mailbox ${data.mailbox.email_address}. You can test it now.` })
      setForm((current) => ({ ...current, smtp_password: '', imap_password: '', resend_api_key: '', resend_webhook_secret: '' }))
      await loadMailboxes(selectedOrganizationId)
    } catch (err: unknown) {
      setFeedback({ type: 'error', message: getErrorMessage(err, 'Failed to save mailbox') })
    } finally {
      setSaving(false)
    }
  }

  const testMailbox = async (mailboxId: number) => {
    if (!selectedOrganizationId || !canManageMailboxes) return
    setTestingId(mailboxId)
    setFeedback(null)
    try {
      const res = await authedFetch(`${API_BASE}/api/organizations/${selectedOrganizationId}/mailboxes/${mailboxId}/test`, {
        method: 'POST',
      })
      const data = await res.json()
      if (!res.ok || data.success === false) {
        throw new Error(data.error || data.detail || 'Mailbox test failed')
      }
      setFeedback({ type: 'success', message: data.message || 'Mailbox test passed.' })
      await loadMailboxes(selectedOrganizationId)
    } catch (err: unknown) {
      setFeedback({ type: 'error', message: getErrorMessage(err, 'Mailbox test failed') })
      await loadMailboxes(selectedOrganizationId)
    } finally {
      setTestingId(null)
    }
  }

  const syncMailbox = async (mailboxId: number) => {
    if (!selectedOrganizationId || !canSyncMailboxes) return
    setSyncingId(mailboxId)
    setFeedback(null)
    setSyncResults((current) => ({ ...current, [mailboxId]: null }))
    try {
      const res = await authedFetch(`${API_BASE}/api/organizations/${selectedOrganizationId}/mailboxes/${mailboxId}/sync?limit=10`, {
        method: 'POST',
      })
      const data = await res.json() as MailboxSyncResponse & { detail?: string; error?: string }
      if (!res.ok) {
        throw new Error(data.detail || data.error || 'Mailbox sync failed')
      }
      const result = mailboxSyncFeedback(data)
      setFeedback(result)
      setSyncResults((current) => ({ ...current, [mailboxId]: result }))
      await loadMailboxes(selectedOrganizationId)
    } catch (err: unknown) {
      const result = { type: 'error' as const, message: getErrorMessage(err, 'Mailbox sync failed') }
      setFeedback(result)
      setSyncResults((current) => ({ ...current, [mailboxId]: result }))
      await loadMailboxes(selectedOrganizationId)
    } finally {
      setSyncingId(null)
    }
  }

  if (!isLoaded || !userId || orgLoading) {
    return <div className="flex items-center justify-center min-h-screen">Loading or unauthorized...</div>
  }

  return (
    <AppShell active="mailboxes">
      <main className="flex-1 max-w-6xl mx-auto w-full p-8">
        <div className="flex items-center justify-between gap-4 mb-6">
          <div>
            <h2 className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">Mailbox Connections</h2>
            <p className="text-sm text-zinc-500 mt-1">Connect an existing mailbox for SMTP sending and IMAP reply monitoring.</p>
          </div>
          <button
            onClick={() => selectedOrganizationId ? void loadMailboxes(selectedOrganizationId) : undefined}
            className="px-3 py-2 border border-zinc-300 rounded-md text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Refresh
          </button>
        </div>

        <ActionFeedback feedback={feedback} onDismiss={() => setFeedback(null)} className="mb-4" />

        <section className="bg-white border border-zinc-200 rounded-lg shadow-sm dark:bg-zinc-900 dark:border-zinc-800 mb-6">
          <div className="p-5 border-b border-zinc-200 dark:border-zinc-800">
            <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">Mailbox Settings</h3>
            <p className="mt-1 text-sm text-zinc-500">
              Active organization: {selectedOrganization ? `${selectedOrganization.name} (${selectedOrganization.slug})` : 'None'}
            </p>
          </div>

          <form onSubmit={submitMailbox} className="p-5">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <label className="block">
                <span className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-1">Provider</span>
                <select
                  value={form.provider}
                  onChange={(event) => updateForm('provider', event.target.value as MailboxForm['provider'])}
                  className="w-full px-3 py-2 border border-zinc-300 rounded-md bg-white dark:bg-zinc-950 dark:border-zinc-700"
                >
                  <option value="smtp_imap">SMTP / IMAP</option>
                  <option value="resend">Resend</option>
                </select>
              </label>
              <TextField label="Display name" value={form.display_name} onChange={(value) => updateForm('display_name', value)} />
              <TextField label="Email address" value={form.email_address} onChange={(value) => updateForm('email_address', value)} type="email" />
              {form.provider === 'smtp_imap' ? (
                <>
                  <TextField label="SMTP host" value={form.smtp_host} onChange={(value) => updateForm('smtp_host', value)} />
                  <TextField label="SMTP port" value={form.smtp_port} onChange={(value) => updateForm('smtp_port', value)} type="number" />
                  <TextField label="SMTP username" value={form.smtp_username} onChange={(value) => updateForm('smtp_username', value)} />
                  <PasswordField label="SMTP password" value={form.smtp_password} onChange={(value) => updateForm('smtp_password', value)} />
                  <TextField label="IMAP host" value={form.imap_host} onChange={(value) => updateForm('imap_host', value)} />
                  <TextField label="IMAP port" value={form.imap_port} onChange={(value) => updateForm('imap_port', value)} type="number" />
                  <TextField label="IMAP username" value={form.imap_username} onChange={(value) => updateForm('imap_username', value)} />
                  <PasswordField label="IMAP password" value={form.imap_password} onChange={(value) => updateForm('imap_password', value)} />
                </>
              ) : (
                <>
                  <TextField label="Resend domain" value={form.resend_domain} onChange={(value) => updateForm('resend_domain', value)} required={false} />
                  <TextField label="Resend from email" value={form.resend_from_email} onChange={(value) => updateForm('resend_from_email', value)} />
                  <TextField label="Resend reply-to" value={form.resend_reply_to} onChange={(value) => updateForm('resend_reply_to', value)} type="email" required={false} />
                  <PasswordField label="Resend API key" value={form.resend_api_key} onChange={(value) => updateForm('resend_api_key', value)} />
                  <PasswordField label="Resend webhook secret" value={form.resend_webhook_secret} onChange={(value) => updateForm('resend_webhook_secret', value)} required={false} />
                  <div className="rounded-md border border-zinc-200 p-3 text-sm text-zinc-600 dark:border-zinc-700 dark:text-zinc-300">
                    Webhook URL after save: <span className="font-mono">/webhooks/email/resend/&lt;mailbox_id&gt;</span>
                  </div>
                </>
              )}
              <TextField label="Daily limit" value={form.daily_limit} onChange={(value) => updateForm('daily_limit', value)} type="number" />

              {form.provider === 'smtp_imap' && <div className="flex items-end gap-5 pb-2">
                <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
                  <input
                    type="checkbox"
                    checked={form.smtp_use_ssl}
                    onChange={(event) => updateForm('smtp_use_ssl', event.target.checked)}
                  />
                  SMTP SSL
                </label>
                <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
                  <input
                    type="checkbox"
                    checked={form.imap_use_ssl}
                    onChange={(event) => updateForm('imap_use_ssl', event.target.checked)}
                  />
                  IMAP SSL
                </label>
              </div>}
            </div>

            <div className="flex justify-end mt-6">
              <button
                type="submit"
                disabled={saving || !selectedOrganizationId || !canManageMailboxes}
                className="px-4 py-2 text-sm font-medium text-white bg-zinc-900 rounded-md hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
              >
                {saving ? 'Saving...' : 'Save Mailbox'}
              </button>
            </div>
          </form>
        </section>

        <section className="bg-white border border-zinc-200 rounded-lg shadow-sm dark:bg-zinc-900 dark:border-zinc-800 overflow-hidden">
          <div className="px-5 py-3 border-b border-zinc-200 dark:border-zinc-800 font-semibold">Connected Mailboxes</div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm min-w-[920px]">
              <thead className="bg-zinc-50 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400">
                <tr>
                  <th className="px-4 py-3 font-medium">Mailbox</th>
                  <th className="px-4 py-3 font-medium">Provider</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Sending</th>
                  <th className="px-4 py-3 font-medium">Receiving</th>
                  <th className="px-4 py-3 font-medium">Last Tested</th>
                  <th className="px-4 py-3 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                {mailboxes.map((mailbox) => (
                  <tr key={mailbox.id}>
                    <td className="px-4 py-3">
                      <div className="font-medium">{mailbox.display_name || mailbox.email_address}</div>
                      <div className="text-xs text-zinc-500">{mailbox.email_address}</div>
                    </td>
                    <td className="px-4 py-3">{mailbox.provider}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-1 rounded text-xs font-medium ${statusClass(mailbox.status)}`}>
                        {mailbox.status}
                      </span>
                      {mailbox.last_error && <div className="text-xs text-red-600 mt-1 max-w-xs">{mailbox.last_error}</div>}
                    </td>
                    <td className="px-4 py-3">
                      {mailbox.provider === 'resend'
                        ? (mailbox.resend_from_email || mailbox.email_address)
                        : `${mailbox.smtp_host}:${mailbox.smtp_port}`}
                    </td>
                    <td className="px-4 py-3">
                      {mailbox.provider === 'resend' ? (
                        <div>
                          <div>{mailbox.resend_domain || '-'}</div>
                          <div className="text-xs text-zinc-500">/webhooks/email/resend/{mailbox.id}</div>
                        </div>
                      ) : `${mailbox.imap_host}:${mailbox.imap_port}`}
                    </td>
                    <td className="px-4 py-3 text-zinc-500">{formatTimestamp(mailbox.last_tested_at, selectedOrganization?.timezone)}</td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2">
                      <button
                        onClick={() => void testMailbox(mailbox.id)}
                        disabled={testingId === mailbox.id || !canManageMailboxes}
                        className="px-3 py-2 border border-zinc-300 rounded-md text-sm font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                      >
                        {testingId === mailbox.id ? 'Testing...' : 'Test'}
                      </button>
                      <button
                        onClick={() => void syncMailbox(mailbox.id)}
                        disabled={syncingId === mailbox.id || mailbox.status !== 'CONNECTED' || mailbox.provider !== 'smtp_imap' || !canSyncMailboxes}
                        className="px-3 py-2 text-sm font-medium text-white bg-zinc-900 rounded-md hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
                      >
                        {syncingId === mailbox.id ? 'Syncing...' : 'Sync'}
                      </button>
                      </div>
                      {syncResults[mailbox.id] && (
                        <div className={`mt-2 max-w-xs text-xs ${syncResults[mailbox.id]?.type === 'error' ? 'text-red-600' : syncResults[mailbox.id]?.type === 'warning' ? 'text-amber-700 dark:text-amber-400' : 'text-emerald-700 dark:text-emerald-400'}`}>
                          {syncResults[mailbox.id]?.message}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
                {!loading && mailboxes.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-6 py-8 text-center text-zinc-500">No mailbox connections yet.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </AppShell>
  )
}

function TextField({
  label,
  value,
  onChange,
  type = 'text',
  required = true,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  type?: string
  required?: boolean
}) {
  return (
    <label className="block">
      <span className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-1">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full px-3 py-2 border border-zinc-300 rounded-md bg-white dark:bg-zinc-950 dark:border-zinc-700"
        required={required}
      />
    </label>
  )
}

function PasswordField({
  label,
  value,
  onChange,
  required = true,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  required?: boolean
}) {
  return (
    <label className="block">
      <span className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-1">{label}</span>
      <input
        type="password"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full px-3 py-2 border border-zinc-300 rounded-md bg-white dark:bg-zinc-950 dark:border-zinc-700"
        autoComplete="new-password"
        required={required}
      />
    </label>
  )
}

function statusClass(status: string) {
  if (status === 'CONNECTED') return 'bg-emerald-100 text-emerald-800'
  if (status === 'FAILED') return 'bg-red-100 text-red-800'
  if (status === 'DISABLED') return 'bg-zinc-200 text-zinc-700'
  return 'bg-amber-100 text-amber-800'
}

async function responseText(res: Response, fallback: string) {
  try {
    const data = await res.json()
    return data.detail || data.error || fallback
  } catch {
    return fallback
  }
}
