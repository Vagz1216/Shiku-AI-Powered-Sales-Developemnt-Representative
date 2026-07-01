'use client'

import { useCallback, useEffect, useState } from 'react'
import { useAuth } from '@clerk/clerk-react'
import { ActionFeedback, type ActionFeedbackState } from '@/components/action-feedback'
import { AppShell } from '@/components/app-shell'
import { useTenantScope } from '@/components/tenant-scope'
import { fetchWithAuthRetry } from '@/lib/auth-fetch'
import { formatTimestamp } from '@/lib/time'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

type MailboxProvider = 'smtp_imap' | 'resend' | 'gmail' | 'microsoft'

interface MailboxProviderDefinition {
  provider: MailboxProvider
  label: string
  connection_type: 'credentials' | 'api_key' | 'oauth'
  status: 'available' | 'planned' | 'disabled'
  supports_sending: boolean
  supports_reply_sync: boolean
  supports_testing: boolean
  supports_webhooks: boolean
  description: string
}

interface Mailbox {
  id: number
  organization_id: number
  provider: MailboxProvider
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
  oauth_token_expires_at: string | null
  oauth_scopes: string | null
  oauth_external_account_id: string | null
  daily_limit: number
  last_tested_at: string | null
  last_error: string | null
  has_smtp_password: boolean
  has_imap_password: boolean
  has_resend_api_key: boolean
  has_resend_webhook_secret: boolean
  has_oauth_refresh_token: boolean
}

interface MailboxForm {
  provider: MailboxProvider
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

const FALLBACK_MAILBOX_PROVIDERS: MailboxProviderDefinition[] = [
  {
    provider: 'smtp_imap',
    label: 'SMTP / IMAP',
    connection_type: 'credentials',
    status: 'available',
    supports_sending: true,
    supports_reply_sync: true,
    supports_testing: true,
    supports_webhooks: false,
    description: 'Use tenant-owned SMTP credentials for sending and IMAP for inbound reply polling.',
  },
  {
    provider: 'resend',
    label: 'Resend',
    connection_type: 'api_key',
    status: 'available',
    supports_sending: true,
    supports_reply_sync: false,
    supports_testing: true,
    supports_webhooks: true,
    description: 'Use a tenant-owned Resend API key for sending and Resend webhooks for inbound events.',
  },
  {
    provider: 'gmail',
    label: 'Google Gmail / Workspace',
    connection_type: 'oauth',
    status: 'planned',
    supports_sending: false,
    supports_reply_sync: false,
    supports_testing: false,
    supports_webhooks: false,
    description: 'OAuth-based Gmail or Google Workspace mailbox connection. OAuth flow is not enabled yet.',
  },
  {
    provider: 'microsoft',
    label: 'Microsoft Outlook / 365',
    connection_type: 'oauth',
    status: 'planned',
    supports_sending: false,
    supports_reply_sync: false,
    supports_testing: false,
    supports_webhooks: false,
    description: 'OAuth-based Outlook or Microsoft 365 mailbox connection. OAuth flow is not enabled yet.',
  },
]

interface MailboxSyncResponse {
  checked?: number
  processed?: unknown[]
  skipped?: unknown[]
  errors?: unknown[]
}

function emptyForm(): MailboxForm {
  return {
    provider: 'smtp_imap',
    display_name: '',
    email_address: '',
    smtp_host: '',
    smtp_port: '465',
    smtp_use_ssl: true,
    smtp_username: '',
    smtp_password: '',
    imap_host: '',
    imap_port: '993',
    imap_use_ssl: true,
    imap_username: '',
    imap_password: '',
    resend_domain: '',
    resend_from_email: '',
    resend_reply_to: '',
    resend_api_key: '',
    resend_webhook_secret: '',
    daily_limit: '100',
  }
}

function getErrorMessage(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback
}

function formFromMailbox(mailbox: Mailbox): MailboxForm {
  return {
    provider: mailbox.provider,
    display_name: mailbox.display_name || '',
    email_address: mailbox.email_address || '',
    smtp_host: mailbox.smtp_host || '',
    smtp_port: mailbox.smtp_port ? String(mailbox.smtp_port) : '465',
    smtp_use_ssl: Boolean(mailbox.smtp_use_ssl),
    smtp_username: mailbox.smtp_username || '',
    smtp_password: '',
    imap_host: mailbox.imap_host || '',
    imap_port: mailbox.imap_port ? String(mailbox.imap_port) : '993',
    imap_use_ssl: Boolean(mailbox.imap_use_ssl),
    imap_username: mailbox.imap_username || '',
    imap_password: '',
    resend_domain: mailbox.resend_domain || '',
    resend_from_email: mailbox.resend_from_email || '',
    resend_reply_to: mailbox.resend_reply_to || '',
    resend_api_key: '',
    resend_webhook_secret: '',
    daily_limit: String(mailbox.daily_limit || 100),
  }
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

function mailboxSendingDisplay(mailbox: Mailbox, definition: MailboxProviderDefinition) {
  if (!definition.supports_sending) return 'Not enabled'
  if (mailbox.provider === 'resend') return mailbox.resend_from_email || mailbox.email_address
  if (mailbox.provider === 'smtp_imap') return `${mailbox.smtp_host || '-'}:${mailbox.smtp_port || '-'}`
  return 'OAuth mailbox'
}

function mailboxReceivingDisplay(mailbox: Mailbox, definition: MailboxProviderDefinition) {
  if (mailbox.provider === 'resend') {
    return (
      <div>
        <div>{mailbox.resend_domain || '-'}</div>
        <div className="text-xs text-zinc-500">/webhooks/email/resend/{mailbox.id}</div>
      </div>
    )
  }
  if (mailbox.provider === 'smtp_imap') return `${mailbox.imap_host || '-'}:${mailbox.imap_port || '-'}`
  return definition.supports_reply_sync ? 'OAuth sync' : 'Not enabled'
}

export default function MailboxesPage() {
  const { isLoaded, userId, getToken } = useAuth()
  const { loading: orgLoading, selectedOrganizationId, selectedOrganization } = useTenantScope()
  const [mailboxes, setMailboxes] = useState<Mailbox[]>([])
  const [form, setForm] = useState<MailboxForm>(() => emptyForm())
  const [editingMailboxId, setEditingMailboxId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testingId, setTestingId] = useState<number | null>(null)
  const [syncingId, setSyncingId] = useState<number | null>(null)
  const [connectingProvider, setConnectingProvider] = useState<MailboxProvider | null>(null)
  const [feedback, setFeedback] = useState<ActionFeedbackState>(null)
  const [syncResults, setSyncResults] = useState<Record<number, ActionFeedbackState>>({})
  const [providerDefinitions, setProviderDefinitions] = useState<MailboxProviderDefinition[]>(FALLBACK_MAILBOX_PROVIDERS)
  const canManageMailboxes = !!selectedOrganization?.capabilities?.can_manage_mailboxes
  const canSyncMailboxes = canManageMailboxes || selectedOrganization?.current_user_role === 'sales_manager'

  const authedFetch = useCallback(async (url: string, init: RequestInit = {}) => {
    return fetchWithAuthRetry(getToken, url, init)
  }, [getToken])

  const loadMailboxProviders = useCallback(async () => {
    try {
      const res = await authedFetch(`${API_BASE}/api/mailbox-providers`)
      if (!res.ok) throw new Error(await responseText(res, 'Failed to load mailbox providers'))
      const data = await res.json() as { providers: MailboxProviderDefinition[] }
      setProviderDefinitions(data.providers?.length ? data.providers : FALLBACK_MAILBOX_PROVIDERS)
    } catch {
      setProviderDefinitions(FALLBACK_MAILBOX_PROVIDERS)
    }
  }, [authedFetch])

  const loadMailboxes = useCallback(async (organizationId: number) => {
    if (!organizationId) return
    setLoading(true)
    try {
      const res = await authedFetch(`${API_BASE}/api/organizations/${organizationId}/mailboxes`)
      if (!res.ok) throw new Error(await responseText(res, 'Failed to load mailboxes'))
      const data = await res.json() as { mailboxes: Mailbox[] }
      setMailboxes((data.mailboxes || []).filter(mailbox => Number(mailbox.organization_id) === Number(organizationId)))
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
        void loadMailboxProviders()
        setEditingMailboxId(null)
        setForm(emptyForm())
        setFeedback(null)
        setSyncResults({})
        void loadMailboxes(selectedOrganizationId)
      }, 0)
      return () => window.clearTimeout(timer)
    }
  }, [isLoaded, userId, selectedOrganizationId, loadMailboxProviders, loadMailboxes])

  useEffect(() => {
    if (isLoaded && userId && !orgLoading && !selectedOrganizationId) {
      const timer = window.setTimeout(() => {
        setMailboxes([])
        setLoading(false)
      }, 0)
      return () => window.clearTimeout(timer)
    }
  }, [isLoaded, orgLoading, selectedOrganizationId, userId])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const oauthStatus = params.get('mailbox_oauth')
    if (!oauthStatus) return
    const timer = window.setTimeout(() => {
      if (oauthStatus === 'connected') {
        setFeedback({ type: 'success', message: 'OAuth mailbox connected. Test it before using it for sending or sync.' })
        if (selectedOrganizationId) void loadMailboxes(selectedOrganizationId)
      } else {
        setFeedback({ type: 'error', message: 'OAuth mailbox connection failed. Check provider settings and try again.' })
      }
      const cleanUrl = `${window.location.pathname}${window.location.hash || ''}`
      window.history.replaceState({}, '', cleanUrl)
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadMailboxes, selectedOrganizationId])

  const updateForm = (field: keyof MailboxForm, value: string | boolean) => {
    setForm((current) => ({ ...current, [field]: value }))
  }

  const editMailbox = (mailbox: Mailbox) => {
    if (Number(mailbox.organization_id) !== Number(selectedOrganizationId)) return
    setEditingMailboxId(mailbox.id)
    setForm(formFromMailbox(mailbox))
    setFeedback(null)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const resetMailboxForm = () => {
    setEditingMailboxId(null)
    setForm(emptyForm())
  }

  const startNewMailbox = () => {
    resetMailboxForm()
    setFeedback(null)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const providerDefinitionFor = useCallback((provider: MailboxProvider) => {
    return providerDefinitions.find(definition => definition.provider === provider)
      || FALLBACK_MAILBOX_PROVIDERS.find(definition => definition.provider === provider)
      || FALLBACK_MAILBOX_PROVIDERS[0]
  }, [providerDefinitions])
  const connectedSendingMailboxes = mailboxes.filter(
    mailbox => mailbox.status === 'CONNECTED' && providerDefinitionFor(mailbox.provider).supports_sending,
  )
  const hasMultipleConnectedSenders = connectedSendingMailboxes.length > 1

  const submitMailbox = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedOrganizationId || !canManageMailboxes) return
    const selectedProviderDefinition = providerDefinitionFor(form.provider)
    if (selectedProviderDefinition.status !== 'available') {
      setFeedback({
        type: 'error',
        message: `${selectedProviderDefinition.label} connections are not enabled yet. OAuth setup needs backend client credentials and callback handling first.`,
      })
      return
    }
    if (form.provider === 'smtp_imap' && form.smtp_use_ssl && Number(form.smtp_port) === 587) {
      setFeedback({
        type: 'error',
        message: 'SMTP port 587 uses STARTTLS. Turn SMTP SSL off for port 587, or use port 465 with SMTP SSL on.',
      })
      return
    }
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
      const matchingMailbox = mailboxes.find(
        mailbox => mailbox.email_address.toLowerCase() === form.email_address.trim().toLowerCase()
      )
      const targetMailboxId = editingMailboxId || matchingMailbox?.id || null
      const url = targetMailboxId
        ? `${API_BASE}/api/organizations/${selectedOrganizationId}/mailboxes/${targetMailboxId}`
        : `${API_BASE}/api/organizations/${selectedOrganizationId}/mailboxes`
      const res = await authedFetch(url, {
        method: targetMailboxId ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error(await responseText(res, 'Failed to save mailbox'))
      const data = await res.json() as { mailbox: Mailbox }
      setFeedback({ type: 'success', message: `${targetMailboxId ? 'Updated' : 'Saved'} mailbox ${data.mailbox.email_address}. Test it before using it for sync or sending.` })
      resetMailboxForm()
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

  const connectOAuthMailbox = async (provider: MailboxProvider) => {
    if (!selectedOrganizationId || !canManageMailboxes) return
    const definition = providerDefinitionFor(provider)
    if (definition.connection_type !== 'oauth' || definition.status !== 'available') {
      setFeedback({
        type: 'error',
        message: `${definition.label} OAuth is not configured on the backend yet.`,
      })
      return
    }
    setConnectingProvider(provider)
    setFeedback(null)
    try {
      const res = await authedFetch(`${API_BASE}/api/organizations/${selectedOrganizationId}/mailboxes/oauth/${provider}/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          display_name: form.display_name || undefined,
          daily_limit: Number(form.daily_limit || 100),
        }),
      })
      const data = await res.json() as { authorization_url?: string; detail?: string; error?: string }
      if (!res.ok || !data.authorization_url) {
        throw new Error(data.detail || data.error || 'Failed to start OAuth connection')
      }
      window.location.href = data.authorization_url
    } catch (err: unknown) {
      setFeedback({ type: 'error', message: getErrorMessage(err, 'Failed to start OAuth connection') })
      setConnectingProvider(null)
    }
  }

  if (!isLoaded || !userId || orgLoading) {
    return <div className="flex items-center justify-center min-h-screen">Loading or unauthorized...</div>
  }

  const smtpModeConflict = form.provider === 'smtp_imap' && form.smtp_use_ssl && Number(form.smtp_port) === 587
  const selectedProviderDefinition = providerDefinitionFor(form.provider)
  const selectedProviderAvailable = selectedProviderDefinition.status === 'available'
  const selectedProviderUsesOAuth = selectedProviderDefinition.connection_type === 'oauth'

  return (
    <AppShell active="mailboxes">
      <main className="flex-1 max-w-6xl mx-auto w-full p-8">
        <div className="flex items-center justify-between gap-4 mb-6">
          <div>
            <h2 className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">Mailbox Connections</h2>
            <p className="text-sm text-zinc-500 mt-1">Connect tenant-owned sending and reply-monitoring mailboxes.</p>
            <p className="text-xs text-zinc-500 mt-2 max-w-3xl">
              Outbound campaigns currently assume a single sending mailbox per organization. Connecting more than one mailbox is best for reply sync or separate operational inboxes, not parallel sending from the same campaign unless lead distribution is added.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={startNewMailbox}
              disabled={!canManageMailboxes}
              className="px-3 py-2 text-sm font-medium text-white bg-zinc-900 rounded-md hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
            >
              Add Mailbox
            </button>
            <button
              type="button"
              onClick={() => selectedOrganizationId ? void loadMailboxes(selectedOrganizationId) : undefined}
              className="px-3 py-2 border border-zinc-300 rounded-md text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              Refresh
            </button>
          </div>
        </div>

        <ActionFeedback feedback={feedback} onDismiss={() => setFeedback(null)} className="mb-4" />

        <section className="bg-white border border-zinc-200 rounded-lg shadow-sm dark:bg-zinc-900 dark:border-zinc-800 mb-6">
          <div className="flex flex-wrap items-start justify-between gap-3 p-5 border-b border-zinc-200 dark:border-zinc-800">
            <div>
              <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
                {editingMailboxId ? `Edit Mailbox #${editingMailboxId}` : 'Add Mailbox'}
              </h3>
              <p className="mt-1 text-sm text-zinc-500">
                Active organization: {selectedOrganization ? `${selectedOrganization.name} (${selectedOrganization.slug})` : 'None'}
              </p>
              {editingMailboxId && (
                <p className="mt-1 text-xs text-zinc-500">
                  Leave password and API key fields blank to keep the currently stored secrets.
                </p>
              )}
            </div>
            {editingMailboxId && (
              <button
                type="button"
                onClick={startNewMailbox}
                disabled={saving || !canManageMailboxes}
                className="px-3 py-2 text-sm font-medium text-white bg-zinc-900 rounded-md hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
              >
                Add Another Mailbox
              </button>
            )}
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
                  {providerDefinitions.map((provider) => (
                    <option key={provider.provider} value={provider.provider}>
                      {provider.label}{provider.status === 'available' ? '' : ' (planned)'}
                    </option>
                  ))}
                </select>
                <span className="mt-1 block text-xs text-zinc-500">
                  {selectedProviderDefinition.description}
                </span>
              </label>
              <TextField label="Display name" value={form.display_name} onChange={(value) => updateForm('display_name', value)} />
              <TextField label="Email address" value={form.email_address} onChange={(value) => updateForm('email_address', value)} type="email" />
              {form.provider === 'smtp_imap' ? (
                <>
                  <TextField label="SMTP host" value={form.smtp_host} onChange={(value) => updateForm('smtp_host', value)} />
                  <TextField label="SMTP port" value={form.smtp_port} onChange={(value) => updateForm('smtp_port', value)} type="number" />
                  {smtpModeConflict && (
                    <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200">
                      Port 587 uses STARTTLS. Turn SMTP SSL off for 587, or use port 465 with SMTP SSL on.
                    </div>
                  )}
                  <TextField label="SMTP username" value={form.smtp_username} onChange={(value) => updateForm('smtp_username', value)} />
                  <PasswordField label="SMTP password" value={form.smtp_password} onChange={(value) => updateForm('smtp_password', value)} required={!editingMailboxId} />
                  <TextField label="IMAP host" value={form.imap_host} onChange={(value) => updateForm('imap_host', value)} />
                  <TextField label="IMAP port" value={form.imap_port} onChange={(value) => updateForm('imap_port', value)} type="number" />
                  <TextField label="IMAP username" value={form.imap_username} onChange={(value) => updateForm('imap_username', value)} />
                  <PasswordField label="IMAP password" value={form.imap_password} onChange={(value) => updateForm('imap_password', value)} required={!editingMailboxId} />
                </>
              ) : form.provider === 'resend' ? (
                <>
                  <TextField label="Resend domain" value={form.resend_domain} onChange={(value) => updateForm('resend_domain', value)} required={false} />
                  <TextField label="Resend from email" value={form.resend_from_email} onChange={(value) => updateForm('resend_from_email', value)} />
                  <TextField label="Resend reply-to" value={form.resend_reply_to} onChange={(value) => updateForm('resend_reply_to', value)} type="email" required={false} />
                  <PasswordField label="Resend API key" value={form.resend_api_key} onChange={(value) => updateForm('resend_api_key', value)} required={!editingMailboxId} />
                  <PasswordField label="Resend webhook secret" value={form.resend_webhook_secret} onChange={(value) => updateForm('resend_webhook_secret', value)} required={false} />
                  <div className="rounded-md border border-zinc-200 p-3 text-sm text-zinc-600 dark:border-zinc-700 dark:text-zinc-300">
                    Webhook URL after save: <span className="font-mono">/webhooks/email/resend/&lt;mailbox_id&gt;</span>
                  </div>
                </>
              ) : (
                <div className="md:col-span-2 rounded-md border border-zinc-200 bg-zinc-50 p-4 text-sm text-zinc-700 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-300">
                  <div className="font-medium text-zinc-900 dark:text-zinc-100">
                    {selectedProviderDefinition.label} OAuth connection is planned.
                  </div>
                  <div className="mt-1">
                    The UI is ready to expose this provider, but saving requires an OAuth callback, client credentials, token storage, and provider-specific send/sync services.
                  </div>
                  <button
                    type="button"
                    onClick={() => void connectOAuthMailbox(selectedProviderDefinition.provider)}
                    disabled={!selectedProviderAvailable || !canManageMailboxes || connectingProvider === selectedProviderDefinition.provider}
                    className="mt-3 px-3 py-2 text-sm font-medium border border-zinc-300 rounded-md hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                  >
                    {connectingProvider === selectedProviderDefinition.provider
                      ? 'Connecting...'
                      : `Connect ${selectedProviderDefinition.provider === 'gmail' ? 'Google' : 'Microsoft'}`}
                  </button>
                  {!selectedProviderAvailable && (
                    <div className="mt-2 text-xs text-zinc-500">
                      Add the provider OAuth client ID and secret to backend environment variables to enable this button.
                    </div>
                  )}
                </div>
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

            <div className="flex flex-wrap justify-end gap-2 mt-6">
              {editingMailboxId && (
                <button
                  type="button"
                  onClick={startNewMailbox}
                  disabled={saving}
                  className="px-4 py-2 text-sm font-medium border border-zinc-300 rounded-md hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                >
                  Add Another
                </button>
              )}
              <button
                type="submit"
                disabled={saving || !selectedOrganizationId || !canManageMailboxes || !selectedProviderAvailable || selectedProviderUsesOAuth}
                className="px-4 py-2 text-sm font-medium text-white bg-zinc-900 rounded-md hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
              >
                {saving ? 'Saving...' : editingMailboxId ? 'Update Mailbox' : 'Save Mailbox'}
              </button>
            </div>
          </form>
        </section>

        <section className="bg-white border border-zinc-200 rounded-lg shadow-sm dark:bg-zinc-900 dark:border-zinc-800 overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 border-b border-zinc-200 dark:border-zinc-800">
            <div>
              <div className="font-semibold">Connected Mailboxes</div>
              {hasMultipleConnectedSenders && (
                <div className="mt-1 text-xs text-amber-700 dark:text-amber-400">
                  {connectedSendingMailboxes.length} sending mailboxes are connected. Outbound campaign sends now require one sender to avoid ambiguous mailbox selection.
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={startNewMailbox}
              disabled={!canManageMailboxes}
              className="px-3 py-2 text-sm font-medium border border-zinc-300 rounded-md hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              Add Mailbox
            </button>
          </div>
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
                {mailboxes.map((mailbox) => {
                  const mailboxProvider = providerDefinitionFor(mailbox.provider)
                  return (
                    <tr key={mailbox.id}>
                      <td className="px-4 py-3">
                        <div className="font-medium">{mailbox.display_name || mailbox.email_address}</div>
                        <div className="text-xs text-zinc-500">{mailbox.email_address}</div>
                      </td>
                      <td className="px-4 py-3">
                        <div>{mailboxProvider.label}</div>
                        {mailboxProvider.status !== 'available' && (
                          <div className="text-xs text-zinc-500">Planned</div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-1 rounded text-xs font-medium ${statusClass(mailbox.status)}`}>
                          {mailbox.status}
                        </span>
                        {mailbox.last_error && <div className="text-xs text-red-600 mt-1 max-w-xs">{mailbox.last_error}</div>}
                      </td>
                      <td className="px-4 py-3">{mailboxSendingDisplay(mailbox, mailboxProvider)}</td>
                      <td className="px-4 py-3">{mailboxReceivingDisplay(mailbox, mailboxProvider)}</td>
                      <td className="px-4 py-3 text-zinc-500">{formatTimestamp(mailbox.last_tested_at, selectedOrganization?.timezone)}</td>
                      <td className="px-4 py-3">
                        <div className="flex gap-2">
                          <button
                            onClick={() => editMailbox(mailbox)}
                            disabled={!canManageMailboxes}
                            className="px-3 py-2 border border-zinc-300 rounded-md text-sm font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => void testMailbox(mailbox.id)}
                            disabled={testingId === mailbox.id || !canManageMailboxes || !mailboxProvider.supports_testing}
                            className="px-3 py-2 border border-zinc-300 rounded-md text-sm font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                          >
                            {testingId === mailbox.id ? 'Testing...' : 'Test'}
                          </button>
                          <button
                            onClick={() => void syncMailbox(mailbox.id)}
                            disabled={syncingId === mailbox.id || mailbox.status !== 'CONNECTED' || !mailboxProvider.supports_reply_sync || !canSyncMailboxes}
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
                  )
                })}
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
