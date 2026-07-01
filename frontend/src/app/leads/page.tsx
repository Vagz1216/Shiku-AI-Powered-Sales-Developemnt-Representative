'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAuth } from "@clerk/clerk-react";
import { AppShell } from '@/components/app-shell'
import { useTenantScope } from '@/components/tenant-scope'
import { fetchWithAuthRetry } from '@/lib/auth-fetch'
import { formatTimestamp } from '@/lib/time'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

const STATUS_OPTIONS = [
  'NEW',
  'CONTACTED',
  'WARM',
  'QUALIFIED',
  'MEETING_PROPOSED',
  'MEETING_BOOKED',
  'COLD',
  'OPTED_OUT',
]

const COUNTRY_CODES = [
  { code: '+1', label: 'US/CA (+1)' },
  { code: '+44', label: 'UK (+44)' },
  { code: '+61', label: 'AU (+61)' },
  { code: '+91', label: 'IN (+91)' },
  { code: '+254', label: 'KE (+254)' },
  { code: '+256', label: 'UG (+256)' },
  { code: '+255', label: 'TZ (+255)' },
  { code: '+250', label: 'RW (+250)' },
  { code: '+234', label: 'NG (+234)' },
  { code: '+27', label: 'ZA (+27)' },
  { code: '+20', label: 'EG (+20)' },
  { code: '+212', label: 'MA (+212)' },
  { code: '+233', label: 'GH (+233)' },
  { code: '+251', label: 'ET (+251)' },
  { code: '+260', label: 'ZM (+260)' },
  { code: '+263', label: 'ZW (+263)' },
  { code: '+244', label: 'AO (+244)' },
  { code: '+49', label: 'DE (+49)' },
  { code: '+33', label: 'FR (+33)' },
  { code: '+39', label: 'IT (+39)' },
  { code: '+34', label: 'ES (+34)' },
  { code: '+31', label: 'NL (+31)' },
  { code: '+32', label: 'BE (+32)' },
  { code: '+41', label: 'CH (+41)' },
  { code: '+43', label: 'AT (+43)' },
  { code: '+46', label: 'SE (+46)' },
  { code: '+47', label: 'NO (+47)' },
  { code: '+45', label: 'DK (+45)' },
  { code: '+358', label: 'FI (+358)' },
  { code: '+48', label: 'PL (+48)' },
  { code: '+971', label: 'AE (+971)' },
  { code: '+966', label: 'SA (+966)' },
  { code: '+974', label: 'QA (+974)' },
  { code: '+90', label: 'TR (+90)' },
  { code: '+55', label: 'BR (+55)' },
  { code: '+52', label: 'MX (+52)' },
  { code: '+54', label: 'AR (+54)' },
  { code: '+57', label: 'CO (+57)' },
  { code: '+56', label: 'CL (+56)' },
  { code: '+51', label: 'PE (+51)' },
  { code: '+81', label: 'JP (+81)' },
  { code: '+86', label: 'CN (+86)' },
  { code: '+92', label: 'PK (+92)' },
  { code: '+880', label: 'BD (+880)' },
  { code: '+62', label: 'ID (+62)' },
  { code: '+63', label: 'PH (+63)' },
  { code: '+65', label: 'SG (+65)' },
  { code: '+60', label: 'MY (+60)' },
  { code: '+66', label: 'TH (+66)' },
  { code: '+84', label: 'VN (+84)' },
  { code: '+82', label: 'KR (+82)' },
]

interface LeadRow {
  id: number
  name: string | null
  email: string
  phone_number: string | null
  linkedin_url: string | null
  company: string | null
  industry: string | null
  pain_points: string | null
  status: string
  touch_count: number
  email_opt_out: number | boolean
  last_contacted_at: string | null
  last_inbound_at: string | null
  created_at: string
  emails_sent: number
  responded: number
  meeting_booked: number
  campaigns: string
  campaign_ids: string
  last_outbound_status: string | null
  last_outbound_subject: string | null
  last_outbound_at: string | null
}

interface CampaignRow {
  id: number
  name: string
  status: string
}

interface LeadFormState {
  email: string
  name: string
  country_code: string
  phone_number: string
  linkedin_url: string
  company: string
  industry: string
  pain_points: string
  status: string
  email_opt_out: boolean
  campaign_ids: number[]
}

const emptyForm: LeadFormState = {
  email: '',
  name: '',
  country_code: '+1',
  phone_number: '',
  linkedin_url: '',
  company: '',
  industry: '',
  pain_points: '',
  status: 'NEW',
  email_opt_out: false,
  campaign_ids: [],
}

function statusBadgeClass(status: string) {
  switch ((status || '').toUpperCase()) {
    case 'MEETING_BOOKED':
      return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
    case 'MEETING_PROPOSED':
    case 'QUALIFIED':
    case 'WARM':
      return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
    case 'CONTACTED':
      return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
    case 'OPTED_OUT':
      return 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-400'
    default:
      return 'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300'
  }
}

function getErrorMessage(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback
}

function parseCampaignIds(value: string | null | undefined) {
  return String(value || '')
    .split(',')
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item) && item > 0)
}

function normalizeImportedLead(row: Record<string, unknown>) {
  const lowered = Object.fromEntries(
    Object.entries(row).map(([key, value]) => [key.trim().toLowerCase(), value])
  )
  const pick = (...keys: string[]) => {
    for (const key of keys) {
      const value = lowered[key]
      if (value !== undefined && value !== null && String(value).trim() !== '') return String(value).trim()
    }
    return ''
  }
  return {
    email: pick('email', 'email_address', 'work_email').toLowerCase(),
    name: pick('name', 'full_name', 'contact_name') || null,
    phone_number: pick('phone_number', 'phone', 'mobile') || null,
    linkedin_url: pick('linkedin_url', 'linkedin', 'linkedin_profile') || null,
    company: pick('company', 'company_name', 'account') || null,
    industry: pick('industry', 'sector') || null,
    pain_points: pick('pain_points', 'pain point', 'notes', 'description') || null,
    status: (pick('status') || 'NEW').toUpperCase(),
    email_opt_out: ['1', 'true', 'yes', 'y'].includes(pick('email_opt_out', 'opt_out', 'unsubscribed').toLowerCase()),
  }
}

function parseCsv(text: string) {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index]
    const next = text[index + 1]
    if (char === '"' && quoted && next === '"') {
      field += '"'
      index += 1
    } else if (char === '"') {
      quoted = !quoted
    } else if (char === ',' && !quoted) {
      row.push(field.trim())
      field = ''
    } else if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && next === '\n') index += 1
      row.push(field.trim())
      if (row.some((cell) => cell.length > 0)) rows.push(row)
      row = []
      field = ''
    } else {
      field += char
    }
  }
  row.push(field.trim())
  if (row.some((cell) => cell.length > 0)) rows.push(row)

  const headers = rows.shift()?.map((header) => header.trim()) || []
  return rows.map((cells) => {
    const record: Record<string, unknown> = {}
    headers.forEach((header, index) => {
      record[header] = cells[index] || ''
    })
    return normalizeImportedLead(record)
  })
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 4 }).format(value || 0)
}

export default function LeadsPage() {
  const { isLoaded, userId, getToken } = useAuth()
  const { selectedOrganizationId, selectedOrganization, orgUrl } = useTenantScope()
  const [leads, setLeads] = useState<LeadRow[]>([])
  const [campaigns, setCampaigns] = useState<CampaignRow[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [query, setQuery] = useState('')
  const [form, setForm] = useState<LeadFormState>(emptyForm)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [importCampaignIds, setImportCampaignIds] = useState<number[]>([])
  const [apiUrl, setApiUrl] = useState('')
  const [jsonPath, setJsonPath] = useState('')
  const [headerName, setHeaderName] = useState('authorization')
  const [headerValue, setHeaderValue] = useState('')
  const [usageCost, setUsageCost] = useState<number | null>(null)
  const [crmProvider, setCrmProvider] = useState('hubspot')
  
  // Bulk selection state
  const [selectedLeadIds, setSelectedLeadIds] = useState<number[]>([])
  const [isDeleting, setIsDeleting] = useState(false)
  
  const canManageLeads = !!selectedOrganization?.capabilities?.can_manage_leads

  const authedFetch = useCallback(async (url: string, init: RequestInit = {}) => {
    const headers = new Headers(init.headers)
    if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
    return fetchWithAuthRetry(getToken, url, { ...init, headers })
  }, [getToken])

  const loadLeads = useCallback(async () => {
    try {
      setLoading(true)
      setError('')
      if (!selectedOrganizationId) return
      const res = await authedFetch(orgUrl(`${API_BASE}/api/leads`))
      if (!res.ok) throw new Error('Failed to load leads')
      const data = await res.json() as { leads?: LeadRow[] }
      setLeads(data.leads || [])
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load leads'))
    } finally {
      setLoading(false)
    }
  }, [authedFetch, orgUrl, selectedOrganizationId])

  const loadCampaigns = useCallback(async () => {
    try {
      if (!selectedOrganizationId) return
      const res = await authedFetch(orgUrl(`${API_BASE}/api/campaigns?active_only=false`))
      if (!res.ok) throw new Error('Failed to load campaigns')
      const data = await res.json() as { campaigns?: CampaignRow[] }
      setCampaigns(data.campaigns || [])
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load campaigns'))
    }
  }, [authedFetch, orgUrl, selectedOrganizationId])

  const loadUsage = useCallback(async () => {
    try {
      if (!selectedOrganizationId) return
      const res = await authedFetch(orgUrl(`${API_BASE}/api/usage/llm?limit=1`))
      if (!res.ok) return
      const data = await res.json() as { total?: { estimated_cost_usd?: number } }
      setUsageCost(Number(data.total?.estimated_cost_usd || 0))
    } catch {
      setUsageCost(null)
    }
  }, [authedFetch, orgUrl, selectedOrganizationId])

  useEffect(() => {
    if (isLoaded && userId && selectedOrganizationId) {
      const timer = window.setTimeout(() => {
        void loadLeads()
        void loadCampaigns()
        void loadUsage()
      }, 0)
      return () => window.clearTimeout(timer)
    }
  }, [isLoaded, userId, selectedOrganizationId, loadLeads, loadCampaigns, loadUsage])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return leads
    return leads.filter((lead) =>
      String(lead.id).includes(q) ||
      (lead.name || '').toLowerCase().includes(q) ||
      lead.email.toLowerCase().includes(q) ||
      (lead.company || '').toLowerCase().includes(q) ||
      (lead.industry || '').toLowerCase().includes(q) ||
      (lead.status || '').toLowerCase().includes(q) ||
      (lead.campaigns || '').toLowerCase().includes(q) ||
      (lead.last_outbound_status || '').toLowerCase().includes(q)
    )
  }, [leads, query])

  const visibleLeadCount = filtered.length
  const visibleLeadIds = useMemo(() => filtered.map(l => l.id), [filtered])
  const allVisibleSelected = visibleLeadIds.length > 0 && visibleLeadIds.every(id => selectedLeadIds.includes(id))

  const toggleLeadSelection = (id: number) => {
    setSelectedLeadIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }

  const toggleAllVisible = () => {
    if (allVisibleSelected) {
      setSelectedLeadIds(prev => prev.filter(id => !visibleLeadIds.includes(id)))
    } else {
      setSelectedLeadIds(prev => Array.from(new Set([...prev, ...visibleLeadIds])))
    }
  }

  const updateCampaignSelection = (campaignId: number, checked: boolean, target: 'form' | 'import') => {
    const updater = (ids: number[]) => checked ? [...new Set([...ids, campaignId])] : ids.filter((id) => id !== campaignId)
    if (target === 'form') {
      setForm((current) => ({ ...current, campaign_ids: updater(current.campaign_ids) }))
    } else {
      setImportCampaignIds((current) => updater(current))
    }
  }

  const resetForm = () => {
    setEditingId(null)
    setForm(emptyForm)
  }

  const startEdit = (lead: LeadRow) => {
    setEditingId(lead.id)
    
    let cc = '+1'
    let phone = lead.phone_number || ''
    for (const country of COUNTRY_CODES) {
      if (phone.startsWith(country.code)) {
        cc = country.code
        phone = phone.substring(country.code.length).trim()
        break
      }
    }

    setForm({
      email: lead.email,
      name: lead.name || '',
      country_code: cc,
      phone_number: phone,
      linkedin_url: lead.linkedin_url || '',
      company: lead.company || '',
      industry: lead.industry || '',
      pain_points: lead.pain_points || '',
      status: lead.status || 'NEW',
      email_opt_out: lead.email_opt_out === true || lead.email_opt_out === 1,
      campaign_ids: parseCampaignIds(lead.campaign_ids),
    })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const saveLead = async () => {
    try {
      setSaving(true)
      setError('')
      setNotice('')
      const url = editingId ? orgUrl(`${API_BASE}/api/leads/${editingId}`) : orgUrl(`${API_BASE}/api/leads`)
      const method = editingId ? 'PUT' : 'POST'
      
      const { country_code, ...restForm } = form
      
      const res = await authedFetch(url, {
        method,
        body: JSON.stringify({
          ...restForm,
          name: restForm.name || null,
          phone_number: restForm.phone_number ? `${country_code}${country_code === '+39' ? restForm.phone_number.trim() : restForm.phone_number.trim().replace(/^0+/, '')}` : null,
          linkedin_url: restForm.linkedin_url || null,
          company: restForm.company || null,
          industry: restForm.industry || null,
          pain_points: restForm.pain_points || null,
        }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || 'Failed to save lead')
      }
      setNotice(editingId ? 'Lead updated.' : 'Lead created.')
      resetForm()
      await loadLeads()
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to save lead'))
    } finally {
      setSaving(false)
    }
  }

  const deleteLead = async (lead: LeadRow) => {
    if (!window.confirm(`Delete ${lead.email}? This removes the lead from campaigns and message history.`)) return
    try {
      setError('')
      setNotice('')
      const res = await authedFetch(orgUrl(`${API_BASE}/api/leads/${lead.id}`), { method: 'DELETE' })
      if (!res.ok) throw new Error('Failed to delete lead')
      setNotice('Lead deleted.')
      await loadLeads()
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to delete lead'))
    }
  }

  const bulkDeleteLeads = async () => {
    if (selectedLeadIds.length === 0) return
    if (!window.confirm(`Delete ${selectedLeadIds.length} selected lead(s)? This removes them from campaigns and message history.`)) return
    try {
      setIsDeleting(true)
      setError('')
      setNotice('')
      const res = await authedFetch(orgUrl(`${API_BASE}/api/leads/bulk-delete`), {
        method: 'POST',
        body: JSON.stringify({ lead_ids: selectedLeadIds })
      })
      if (!res.ok) throw new Error('Failed to bulk delete leads')
      setNotice(`Deleted ${selectedLeadIds.length} lead(s).`)
      setSelectedLeadIds([])
      await loadLeads()
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to bulk delete leads'))
    } finally {
      setIsDeleting(false)
    }
  }

  const importLeads = async (incoming: unknown[], source: string) => {
    const leadsToImport = incoming.filter((lead) => typeof lead === 'object' && lead !== null)
    const res = await authedFetch(orgUrl(`${API_BASE}/api/leads/import`), {
      method: 'POST',
      body: JSON.stringify({
        leads: leadsToImport,
        campaign_ids: importCampaignIds,
        upsert: true,
        source,
      }),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail || 'Import failed')
    }
    return await res.json() as { created: number; updated: number; skipped: number }
  }

  const handleFileImport = async (file: File | null) => {
    if (!file) return
    try {
      setSaving(true)
      setError('')
      setNotice('')
      const text = await file.text()
      let rows: unknown[] = []
      if (file.name.toLowerCase().endsWith('.json')) {
        const parsed = JSON.parse(text)
        rows = Array.isArray(parsed) ? parsed : parsed.leads || parsed.data || parsed.records || []
        rows = rows.map((row) => normalizeImportedLead(row as Record<string, unknown>))
      } else {
        rows = parseCsv(text)
      }
      const summary = await importLeads(rows, file.name)
      setNotice(`Imported ${summary.created} new and updated ${summary.updated}; skipped ${summary.skipped}.`)
      await loadLeads()
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to import file'))
    } finally {
      setSaving(false)
    }
  }

  const handleApiImport = async () => {
    try {
      setSaving(true)
      setError('')
      setNotice('')
      const headers: Record<string, string> = {}
      if (headerValue.trim()) headers[headerName] = headerValue.trim()
      const res = await authedFetch(orgUrl(`${API_BASE}/api/leads/import/url`), {
        method: 'POST',
        body: JSON.stringify({
          source_url: apiUrl,
          json_path: jsonPath || null,
          headers,
          campaign_ids: importCampaignIds,
          upsert: true,
        }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || 'API import failed')
      }
      const summary = await res.json() as { created: number; updated: number; skipped: number }
      setNotice(`Imported ${summary.created} new and updated ${summary.updated}; skipped ${summary.skipped}.`)
      setApiUrl('')
      setJsonPath('')
      setHeaderValue('')
      await loadLeads()
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to import from API'))
    } finally {
      setSaving(false)
    }
  }

  const handleCrmImport = async () => {
    try {
      setSaving(true)
      setError('')
      setNotice('')
      const res = await authedFetch(orgUrl(`${API_BASE}/api/integrations/crm/import`), {
        method: 'POST',
        body: JSON.stringify({
          provider: crmProvider,
          campaign_ids: importCampaignIds,
          upsert: true,
          limit: 100,
        }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || 'CRM import failed')
      }
      const summary = await res.json() as { created: number; updated: number; skipped: number }
      setNotice(`CRM import created ${summary.created}, updated ${summary.updated}, skipped ${summary.skipped}.`)
      await loadLeads()
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to import from CRM'))
    } finally {
      setSaving(false)
    }
  }

  const downloadLeadsCsv = async () => {
    try {
      const res = await authedFetch(orgUrl(`${API_BASE}/api/leads/export.csv`))
      if (!res.ok) throw new Error('Export failed')
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'leads-export.csv'
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to export leads'))
    }
  }

  if (!isLoaded || !userId) {
    return <div className="flex items-center justify-center min-h-screen">Loading or unauthorized...</div>
  }

  return (
    <AppShell active="leads">
      <main className="flex-1 max-w-[96rem] mx-auto w-full p-8">
        <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-4 mb-6">
          <div>
            <h2 className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">Lead Operations</h2>
            <p className="text-sm text-zinc-500 mt-1">
              {visibleLeadCount} visible leads{usageCost !== null ? ` · estimated LLM spend ${formatCurrency(usageCost)}` : ''}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {selectedLeadIds.length > 0 && (
              <button
                disabled={isDeleting || !canManageLeads}
                onClick={() => void bulkDeleteLeads()}
                className="px-3 py-2 bg-rose-600 text-white rounded-md text-sm font-medium hover:bg-rose-700 disabled:opacity-50"
              >
                {isDeleting ? 'Deleting...' : `Delete Selected (${selectedLeadIds.length})`}
              </button>
            )}
            <input
              type="text"
              placeholder="Search lead, campaign, email, status..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full sm:w-80 px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700"
            />
            <button
              onClick={() => { void loadLeads(); void loadUsage() }}
              className="px-3 py-2 border border-zinc-300 rounded-md text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              Refresh
            </button>
            <button
              onClick={() => void downloadLeadsCsv()}
              className="px-3 py-2 bg-zinc-900 text-white rounded-md text-sm font-medium dark:bg-zinc-100 dark:text-zinc-900"
            >
              Export CSV
            </button>
          </div>
        </div>

        {error && <div className="p-4 mb-4 text-red-700 bg-red-100 rounded-lg">{error}</div>}
        {notice && <div className="p-4 mb-4 text-emerald-700 bg-emerald-100 rounded-lg">{notice}</div>}

        <section className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(360px,420px)] gap-6 mb-6">
          <div className="bg-white border border-zinc-200 rounded-lg shadow-sm dark:bg-zinc-900 dark:border-zinc-800 p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">{editingId ? `Edit Lead #${editingId}` : 'Add Lead'}</h3>
              {editingId && (
                <button onClick={resetForm} className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100">Cancel edit</button>
              )}
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <input className="px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700" placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
              <input className="px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700" placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              <div className="flex gap-2">
                <select className="w-40 px-2 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700" value={form.country_code} onChange={(e) => setForm({ ...form, country_code: e.target.value })}>
                  {COUNTRY_CODES.map(c => (
                    <option key={c.code} value={c.code}>{c.label}</option>
                  ))}
                </select>
                <input className="flex-1 px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700" placeholder="Phone Number" value={form.phone_number} onChange={(e) => setForm({ ...form, phone_number: e.target.value })} />
              </div>
              <input className="px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700" placeholder="LinkedIn URL" value={form.linkedin_url} onChange={(e) => setForm({ ...form, linkedin_url: e.target.value })} />
              <input className="px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700" placeholder="Company" value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} />
              <input className="px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700" placeholder="Industry" value={form.industry} onChange={(e) => setForm({ ...form, industry: e.target.value })} />
              <select className="px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                {STATUS_OPTIONS.map((status) => <option key={status} value={status}>{status}</option>)}
              </select>
              <label className="flex items-center gap-2 px-3 py-2 border rounded-md dark:border-zinc-700">
                <input type="checkbox" checked={form.email_opt_out} onChange={(e) => setForm({ ...form, email_opt_out: e.target.checked })} />
                <span className="text-sm">Email opt-out</span>
              </label>
              <textarea className="md:col-span-2 px-3 py-2 border rounded-md min-h-20 dark:bg-zinc-800 dark:border-zinc-700" placeholder="Pain points or notes" value={form.pain_points} onChange={(e) => setForm({ ...form, pain_points: e.target.value })} />
            </div>
            <div className="mt-4">
              <div className="text-xs font-medium uppercase tracking-wide text-zinc-500 mb-2">Campaign Assignment</div>
              <div className="flex flex-wrap gap-2">
                {campaigns.map((campaign) => (
                  <label key={campaign.id} className="inline-flex items-center gap-2 px-3 py-1.5 border border-zinc-300 rounded-md text-sm dark:border-zinc-700">
                    <input
                      type="checkbox"
                      checked={form.campaign_ids.includes(campaign.id)}
                      onChange={(e) => updateCampaignSelection(campaign.id, e.target.checked, 'form')}
                    />
                    {campaign.name}
                  </label>
                ))}
                {campaigns.length === 0 && <span className="text-sm text-zinc-500">No campaigns available.</span>}
              </div>
            </div>
            <button
              disabled={saving || !form.email.trim() || !canManageLeads}
              onClick={() => void saveLead()}
              className="mt-5 px-4 py-2 bg-zinc-900 text-white rounded-md text-sm font-medium disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
            >
              {saving ? 'Saving...' : editingId ? 'Update Lead' : 'Create Lead'}
            </button>
          </div>

          <div className="bg-white border border-zinc-200 rounded-lg shadow-sm dark:bg-zinc-900 dark:border-zinc-800 p-5">
            <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-100 mb-4">Bulk Import</h3>
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium uppercase tracking-wide text-zinc-500 mb-2">Assign Imported Leads</label>
                <div className="flex flex-wrap gap-2">
                  {campaigns.map((campaign) => (
                    <label key={campaign.id} className="inline-flex items-center gap-2 px-3 py-1.5 border border-zinc-300 rounded-md text-sm dark:border-zinc-700">
                      <input
                        type="checkbox"
                        checked={importCampaignIds.includes(campaign.id)}
                        onChange={(e) => updateCampaignSelection(campaign.id, e.target.checked, 'import')}
                      />
                      {campaign.name}
                    </label>
                  ))}
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-2">CSV or JSON file</label>
                <input
                  type="file"
                  accept=".csv,.json,text/csv,application/json"
                  disabled={saving || !canManageLeads}
                  onChange={(e) => void handleFileImport(e.target.files?.[0] || null)}
                  className="block w-full text-sm text-zinc-600 dark:text-zinc-300"
                />
              </div>
              <div className="border-t border-zinc-200 dark:border-zinc-800 pt-4 space-y-3">
                <input className="w-full px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700" placeholder="External API URL" value={apiUrl} onChange={(e) => setApiUrl(e.target.value)} />
                <input className="w-full px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700" placeholder="JSON path, e.g. data.leads" value={jsonPath} onChange={(e) => setJsonPath(e.target.value)} />
                <div className="grid grid-cols-[140px_minmax(0,1fr)] gap-2">
                  <select className="px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700" value={headerName} onChange={(e) => setHeaderName(e.target.value)}>
                    <option value="authorization">Authorization</option>
                    <option value="x-api-key">X-API-Key</option>
                    <option value="accept">Accept</option>
                  </select>
                  <input className="px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700" placeholder="Optional header value" value={headerValue} onChange={(e) => setHeaderValue(e.target.value)} />
                </div>
                <button
                  disabled={saving || !apiUrl.trim() || !canManageLeads}
                  onClick={() => void handleApiImport()}
                  className="px-4 py-2 bg-zinc-900 text-white rounded-md text-sm font-medium disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
                >
                  Import From API
                </button>
              </div>
              <div className="border-t border-zinc-200 dark:border-zinc-800 pt-4 space-y-3">
                <div className="grid grid-cols-[140px_minmax(0,1fr)] gap-2">
                  <select className="px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700" value={crmProvider} onChange={(e) => setCrmProvider(e.target.value)}>
                    <option value="hubspot">HubSpot</option>
                  </select>
                  <button
                    disabled={saving || !canManageLeads}
                    onClick={() => void handleCrmImport()}
                    className="px-4 py-2 bg-zinc-900 text-white rounded-md text-sm font-medium disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
                  >
                    Import From CRM
                  </button>
                </div>
                <p className="text-xs text-zinc-500">Uses CRM_PROVIDER/CRM_API_KEY on the backend and assigns contacts to the selected campaigns.</p>
              </div>
            </div>
          </div>
        </section>

        <div className="bg-white border border-zinc-200 rounded-lg shadow-sm dark:bg-zinc-900 dark:border-zinc-800 overflow-hidden">
          {loading ? (
            <p className="p-6 text-zinc-500">Loading leads...</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm min-w-[1320px]">
                <thead className="bg-zinc-50 border-b border-zinc-200 dark:bg-zinc-800 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400">
                  <tr>
                    <th className="px-4 py-3 font-medium w-12 text-center">
                      <input
                        type="checkbox"
                        checked={allVisibleSelected}
                        onChange={toggleAllVisible}
                        className="rounded border-zinc-300 text-indigo-600 focus:ring-indigo-500 dark:border-zinc-600 dark:bg-zinc-700"
                      />
                    </th>
                    <th className="px-4 py-3 font-medium">Lead</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium">Campaign(s)</th>
                    <th className="px-4 py-3 font-medium">Emails</th>
                    <th className="px-4 py-3 font-medium">Touches</th>
                    <th className="px-4 py-3 font-medium">Responded</th>
                    <th className="px-4 py-3 font-medium">Meeting</th>
                    <th className="px-4 py-3 font-medium">Last Outbound</th>
                    <th className="px-4 py-3 font-medium">Last Inbound</th>
                    <th className="px-4 py-3 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                  {filtered.map((lead) => (
                    <tr key={lead.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/50 align-top">
                      <td className="px-4 py-3 text-center">
                        <input
                          type="checkbox"
                          checked={selectedLeadIds.includes(lead.id)}
                          onChange={() => toggleLeadSelection(lead.id)}
                          className="rounded border-zinc-300 text-indigo-600 focus:ring-indigo-500 dark:border-zinc-600 dark:bg-zinc-700"
                        />
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-zinc-900 dark:text-zinc-100">
                          {lead.name || 'Unknown'} <span className="text-zinc-500">#{lead.id}</span>
                        </div>
                        <div className="text-xs text-zinc-500">{lead.email}</div>
                        <div className="text-xs text-zinc-500">{lead.company || 'No company'}{lead.industry ? ` / ${lead.industry}` : ''}</div>
                        {(lead.phone_number || lead.linkedin_url) && (
                          <div className="mt-1 flex gap-2 text-xs text-zinc-400">
                            {lead.phone_number && <span title={lead.phone_number}>📞</span>}
                            {lead.linkedin_url && <a href={lead.linkedin_url} target="_blank" rel="noopener noreferrer" className="hover:text-blue-500">🔗</a>}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${statusBadgeClass(lead.status)}`}>
                          {lead.status}
                        </span>
                        {(lead.email_opt_out === 1 || lead.email_opt_out === true) && (
                          <div className="text-xs text-rose-500 mt-1">Opted out</div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300">{lead.campaigns || '-'}</td>
                      <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300">{lead.emails_sent || 0}</td>
                      <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300">{lead.touch_count || 0}</td>
                      <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300">{lead.responded ? 'Yes' : 'No'}</td>
                      <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300">{lead.meeting_booked ? 'Booked' : '-'}</td>
                      <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300">
                        <div>{lead.last_outbound_status || '-'}</div>
                        <div className="text-xs text-zinc-500 truncate max-w-[220px]">{lead.last_outbound_subject || '-'}</div>
                        <div className="text-xs text-zinc-500">{formatTimestamp(lead.last_outbound_at, selectedOrganization?.timezone)}</div>
                      </td>
                      <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300">{formatTimestamp(lead.last_inbound_at, selectedOrganization?.timezone)}</td>
                      <td className="px-4 py-3">
                        <div className="flex gap-2">
                          <button disabled={!canManageLeads} onClick={() => startEdit(lead)} className="px-3 py-1.5 border border-zinc-300 rounded-md text-xs font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800">Edit</button>
                          <button disabled={!canManageLeads} onClick={() => void deleteLead(lead)} className="px-3 py-1.5 border border-rose-300 text-rose-700 rounded-md text-xs font-medium hover:bg-rose-50 disabled:opacity-50 dark:border-rose-800 dark:text-rose-400 dark:hover:bg-rose-950/30">Delete</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {filtered.length === 0 && (
                    <tr>
                      <td colSpan={11} className="px-6 py-8 text-center text-zinc-500">
                        No leads found for this filter.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>
    </AppShell>
  )
}
