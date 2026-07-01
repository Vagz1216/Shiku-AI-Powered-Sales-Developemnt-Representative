'use client'

import { useCallback, useEffect, useState } from 'react'
import { useAuth } from "@clerk/clerk-react";
import { AppShell } from '@/components/app-shell'
import { ActionFeedback, type ActionFeedbackState } from '@/components/action-feedback'
import { useTenantScope } from '@/components/tenant-scope'
import { fetchWithAuthRetry } from '@/lib/auth-fetch'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Campaign {
  id: number
  name: string
  value_proposition: string
  cta: string
  status: string
  meeting_delay_days: number
  max_leads_per_campaign: number | null
  lead_selection_order: string
  auto_approve_drafts: boolean
  auto_approve_monitor_replies: boolean
  max_emails_per_lead: number
  llm_routing_mode: string | null
  staff_names?: string[]
}

interface CampaignLead {
  id: number
  name: string
  email: string
  company: string | null
  status: string
  touch_count: number
  assigned: number
  emails_sent: number
  responded: number
  meeting_booked: number
}

interface ScoutProviderStatus {
  name: string
  status: string
  reason?: string
  message?: string
}

interface ScoutCandidate {
  name?: string | null
  email?: string | null
  phone_number?: string | null
  linkedin_url?: string | null
  company?: string | null
  industry?: string | null
  pain_points?: string | null
  job_title?: string | null
  seniority?: string | null
  location?: string | null
  company_size?: string | null
  company_website?: string | null
  company_description?: string | null
  recent_activity?: string | null
  status?: string
  campaign_ids?: number[]
  enrichment_source?: string | null
}

interface ScoutJobResult {
  status?: string
  error?: string
  candidates_found: number
  leads_imported: number
  candidates?: ScoutCandidate[]
  provider_statuses?: ScoutProviderStatus[]
}

interface CreditApprovalDetail {
  code?: string
  message?: string
  estimated_max_credits?: number
  provider_statuses?: ScoutProviderStatus[]
}

interface PendingScoutApproval {
  campaign: Campaign
  estimatedMaxCredits: number
  providerStatuses: ScoutProviderStatus[]
  message: string
}

interface SequenceStep {
  id?: number
  step_number: number
  delay_days: number
  subject_template: string
  body_template: string
  active: boolean | number
  channel: 'email' | 'linkedin' | 'whatsapp'
  prompt_context: string
}

function getErrorMessage(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback
}

function routingModeLabel(mode: string | null | undefined) {
  if (!mode) return 'Global default'
  return mode.replace('_', ' ')
}

function scoutFailureMessage(result: ScoutJobResult) {
  const reasons = (result.provider_statuses || [])
    .filter(provider => provider.status === 'failed' || provider.status === 'skipped')
    .map(provider => `${provider.name}: ${provider.reason || provider.status}`)

  if (reasons.length === 0) {
    return result.error || 'Lead Scout did not return candidates.'
  }
  return `${result.error || 'Lead Scout did not return candidates.'} ${reasons.join('; ')}.`
}

function isCreditApprovalDetail(value: unknown): value is CreditApprovalDetail {
  return typeof value === 'object' && value !== null && (value as CreditApprovalDetail).code === 'credit_approval_required'
}

function isMockCandidate(candidate: ScoutCandidate) {
  return (candidate.enrichment_source || '').toLowerCase().includes('mock')
}

export default function CampaignsPage() {
  const { isLoaded, userId, getToken } = useAuth()
  const { selectedOrganizationId, selectedOrganization, orgUrl } = useTenantScope()
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [feedback, setFeedback] = useState<ActionFeedbackState>(null)

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingCampaign, setEditingCampaign] = useState<Campaign | null>(null)
  const [isLeadsModalOpen, setIsLeadsModalOpen] = useState(false)
  const [leadCampaign, setLeadCampaign] = useState<Campaign | null>(null)
  const [campaignLeads, setCampaignLeads] = useState<CampaignLead[]>([])
  const [selectedLeadIds, setSelectedLeadIds] = useState<number[]>([])
  const [leadsSaving, setLeadsSaving] = useState(false)
  const [isSequenceModalOpen, setIsSequenceModalOpen] = useState(false)
  const [sequenceCampaign, setSequenceCampaign] = useState<Campaign | null>(null)
  const [sequenceSteps, setSequenceSteps] = useState<SequenceStep[]>([])
  const [sequenceSaving, setSequenceSaving] = useState(false)
  const [sequenceFeedback, setSequenceFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null)
  const [campaignSaving, setCampaignSaving] = useState(false)
  const [scoutingCampaignId, setScoutingCampaignId] = useState<number | null>(null)
  
  // New state for reviewing scouted leads
  const [scoutCandidates, setScoutCandidates] = useState<ScoutCandidate[] | null>(null)
  const [selectedCandidateIndices, setSelectedCandidateIndices] = useState<number[]>([])
  const [importingCandidates, setImportingCandidates] = useState(false)
  const [pendingScoutApproval, setPendingScoutApproval] = useState<PendingScoutApproval | null>(null)
  const hasMockScoutCandidates = Boolean(scoutCandidates?.some(isMockCandidate))

  // Form State
  const [formData, setFormData] = useState({
    name: '',
    value_proposition: '',
    cta: '',
    status: 'ACTIVE',
    meeting_delay_days: 1,
    max_leads_per_campaign: '',
    lead_selection_order: 'newest_first',
    auto_approve_drafts: false,
    auto_approve_monitor_replies: false,
    max_emails_per_lead: 5,
    llm_routing_mode: ''
  })
  const canManageCampaigns = !!selectedOrganization?.capabilities?.can_manage_campaigns

  const authedFetch = useCallback((url: string, init: RequestInit = {}) => {
    return fetchWithAuthRetry(getToken, url, init)
  }, [getToken])

  const loadCampaigns = useCallback(async () => {
    try {
      if (!selectedOrganizationId) return
      setLoading(true)
      const res = await authedFetch(orgUrl(`${API_BASE}/api/campaigns?active_only=false`))
      if (!res.ok) throw new Error('Failed to fetch campaigns')
      const data = await res.json() as { campaigns?: Campaign[] }
      setCampaigns((data.campaigns || []).map(campaign => ({
        ...campaign,
        staff_names: campaign.staff_names || [],
      })))
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to fetch campaigns'))
    } finally {
      setLoading(false)
    }
  }, [authedFetch, orgUrl, selectedOrganizationId])

  useEffect(() => {
    if (isLoaded && userId && selectedOrganizationId) {
      const timer = window.setTimeout(() => {
        void loadCampaigns()
      }, 0)
      return () => window.clearTimeout(timer)
    }
  }, [isLoaded, userId, selectedOrganizationId, loadCampaigns])

  const handleDelete = async (id: number) => {
    if (!canManageCampaigns) return
    if (!confirm('Are you sure you want to delete this campaign?')) return
    try {
      setFeedback(null)
      const res = await authedFetch(orgUrl(`${API_BASE}/api/campaigns/${id}`), {
        method: 'DELETE',
      })
      if (!res.ok) throw new Error('Failed to delete')
      setCampaigns(current => current.filter(c => c.id !== id))
      setFeedback({ type: 'success', message: 'Campaign deleted.' })
    } catch (err: unknown) {
      setFeedback({ type: 'error', message: getErrorMessage(err, 'Failed to delete campaign') })
    }
  }

  const openCreateModal = () => {
    if (!canManageCampaigns) return
    setFeedback(null)
    setEditingCampaign(null)
    setFormData({
      name: '',
      value_proposition: '',
      cta: '',
      status: 'ACTIVE',
      meeting_delay_days: 1,
      max_leads_per_campaign: '',
      lead_selection_order: 'newest_first',
      auto_approve_drafts: false,
      auto_approve_monitor_replies: false,
      max_emails_per_lead: 5,
      llm_routing_mode: ''
    })
    setIsModalOpen(true)
  }

  const openEditModal = (campaign: Campaign) => {
    if (!canManageCampaigns) return
    setFeedback(null)
    setEditingCampaign(campaign)
    setFormData({
      name: campaign.name,
      value_proposition: campaign.value_proposition,
      cta: campaign.cta,
      status: campaign.status,
      meeting_delay_days: campaign.meeting_delay_days,
      max_leads_per_campaign: campaign.max_leads_per_campaign?.toString() || '',
      lead_selection_order: campaign.lead_selection_order,
      auto_approve_drafts: campaign.auto_approve_drafts,
      auto_approve_monitor_replies: campaign.auto_approve_monitor_replies,
      max_emails_per_lead: campaign.max_emails_per_lead,
      llm_routing_mode: campaign.llm_routing_mode || ''
    })
    setIsModalOpen(true)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canManageCampaigns) return
    try {
      setCampaignSaving(true)
      setFeedback(null)
      setError('')
      const payload = {
        ...formData,
        max_leads_per_campaign: formData.max_leads_per_campaign ? parseInt(formData.max_leads_per_campaign) : null,
        meeting_delay_days: formData.meeting_delay_days,
        max_emails_per_lead: formData.max_emails_per_lead,
        llm_routing_mode: formData.llm_routing_mode || null
      }

      const url = editingCampaign 
        ? orgUrl(`${API_BASE}/api/campaigns/${editingCampaign.id}`)
        : orgUrl(`${API_BASE}/api/campaigns`)
        
      const res = await authedFetch(url, {
        method: editingCampaign ? 'PUT' : 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      })

      if (!res.ok) {
        const text = await res.text()
        let detail = text.slice(0, 500)
        try {
          const j = JSON.parse(text)
          if (j?.detail != null) {
            detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
          }
        } catch {
          /* use raw */
        }
        throw new Error(`Failed to save campaign (${res.status}): ${detail}`)
      }

      const data = await res.json() as { campaign?: Campaign }
      const savedCampaign = data.campaign
      if (savedCampaign) {
        const preservedStaffNames = editingCampaign?.staff_names || []
        const normalizedCampaign: Campaign = {
          ...savedCampaign,
          staff_names: savedCampaign.staff_names || preservedStaffNames,
        }
        setCampaigns(current => {
          const existingIndex = current.findIndex(campaign => campaign.id === normalizedCampaign.id)
          if (existingIndex === -1) {
            return [normalizedCampaign, ...current]
          }
          return current.map(campaign => (
            campaign.id === normalizedCampaign.id
              ? { ...campaign, ...normalizedCampaign, staff_names: normalizedCampaign.staff_names || campaign.staff_names || [] }
              : campaign
          ))
        })
      } else {
        await loadCampaigns()
      }
      setIsModalOpen(false)
      setFeedback({
        type: 'success',
        message: editingCampaign ? `Saved changes to ${payload.name}.` : `Created campaign ${payload.name}.`,
      })
    } catch (err: unknown) {
      setFeedback({ type: 'error', message: getErrorMessage(err, 'Failed to save campaign') })
    } finally {
      setCampaignSaving(false)
    }
  }

  const openLeadsModal = async (campaign: Campaign) => {
    try {
      setLeadCampaign(campaign)
      setIsLeadsModalOpen(true)
      const res = await authedFetch(orgUrl(`${API_BASE}/api/campaigns/${campaign.id}/leads`))
      if (!res.ok) throw new Error('Failed to load campaign leads')
      const data = await res.json() as { leads?: CampaignLead[] }
      const leads: CampaignLead[] = data.leads || []
      setCampaignLeads(leads)
      setSelectedLeadIds(leads.filter(l => !!l.assigned).map(l => l.id))
    } catch (err: unknown) {
      alert(getErrorMessage(err, 'Failed to load campaign leads'))
      setIsLeadsModalOpen(false)
    }
  }

  const toggleLeadSelection = (leadId: number) => {
    setSelectedLeadIds(prev => prev.includes(leadId) ? prev.filter(id => id !== leadId) : [...prev, leadId])
  }

  const saveLeadAssignments = async () => {
    if (!leadCampaign || !canManageCampaigns) return
    try {
      setLeadsSaving(true)
      const res = await authedFetch(orgUrl(`${API_BASE}/api/campaigns/${leadCampaign.id}/leads`), {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ lead_ids: selectedLeadIds })
      })
      if (!res.ok) throw new Error('Failed to save lead assignments')
      setIsLeadsModalOpen(false)
      setFeedback({ type: 'success', message: `Saved ${selectedLeadIds.length} lead assignment${selectedLeadIds.length === 1 ? '' : 's'} for ${leadCampaign.name}.` })
    } catch (err: unknown) {
      setFeedback({ type: 'error', message: getErrorMessage(err, 'Failed to save lead assignments') })
    } finally {
      setLeadsSaving(false)
    }
  }

  const openSequenceModal = async (campaign: Campaign) => {
    try {
      setSequenceCampaign(campaign)
      setSequenceFeedback(null)
      setIsSequenceModalOpen(true)
      const res = await authedFetch(orgUrl(`${API_BASE}/api/campaigns/${campaign.id}/sequence`))
      if (!res.ok) {
        const data = await res.json().catch(() => null) as { detail?: string } | null
        throw new Error(data?.detail || 'Failed to load follow-up sequence')
      }
      const data = await res.json() as { steps?: SequenceStep[] }
      setSequenceSteps((data.steps || []).map(step => ({ ...step, active: !!step.active, channel: (step.channel || 'email') as 'email' | 'linkedin' | 'whatsapp', prompt_context: step.prompt_context || '' })))
    } catch (err: unknown) {
      setFeedback({ type: 'error', message: getErrorMessage(err, 'Failed to load follow-up sequence') })
      setIsSequenceModalOpen(false)
    }
  }

  const updateSequenceStep = (index: number, updates: Partial<SequenceStep>) => {
    setSequenceSteps(current => current.map((step, i) => i === index ? { ...step, ...updates } : step))
  }

  const addSequenceStep = () => {
    const next = Math.max(0, ...sequenceSteps.map(step => Number(step.step_number) || 0)) + 1
    setSequenceSteps(current => [...current, {
      step_number: next,
      delay_days: 3,
      channel: 'email',
      prompt_context: '',
      subject_template: 'Re: {campaign_name}',
      body_template: 'Hi {name},\n\nFollowing up on my previous note about {value_proposition}.\n\n{cta}\n\nBest,\n{sender_name}',
      active: true,
    }])
  }

  const saveSequence = async () => {
    if (!sequenceCampaign || !canManageCampaigns) return
    try {
      setSequenceSaving(true)
      setSequenceFeedback(null)
      const res = await authedFetch(orgUrl(`${API_BASE}/api/campaigns/${sequenceCampaign.id}/sequence`), {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          steps: sequenceSteps.map(step => ({
            step_number: Number(step.step_number) || 1,
            delay_days: Number(step.delay_days) || 1,
            channel: step.channel || 'email',
            prompt_context: step.prompt_context || '',
            subject_template: step.subject_template || '',
            body_template: step.body_template || '',
            active: !!step.active,
          })),
        })
      })
      if (!res.ok) {
        const data = await res.json().catch(() => null) as { detail?: string | unknown[] } | null
        const detail = Array.isArray(data?.detail)
          ? data.detail.map(item => JSON.stringify(item)).join('; ')
          : data?.detail
        throw new Error(detail || 'Failed to save follow-up sequence')
      }
      const data = await res.json() as { steps?: SequenceStep[] }
      const savedSteps = (data.steps || []).map(step => ({ ...step, active: !!step.active, channel: (step.channel || 'email') as 'email' | 'linkedin' | 'whatsapp', prompt_context: step.prompt_context || '' }))
      setSequenceSteps(savedSteps)
      setSequenceFeedback({
        type: 'success',
        message: `✓ Saved ${savedSteps.length} step${savedSteps.length === 1 ? '' : 's'} for "${sequenceCampaign.name}".`,
      })
    } catch (err: unknown) {
      setSequenceFeedback({ type: 'error', message: getErrorMessage(err, 'Failed to save follow-up sequence') })
    } finally {
      setSequenceSaving(false)
    }
  }

  const exportCampaignResults = async (campaign: Campaign) => {
    try {
      const res = await authedFetch(orgUrl(`${API_BASE}/api/campaigns/${campaign.id}/results/export.csv`))
      if (!res.ok) throw new Error('Export failed')
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `campaign-${campaign.id}-results.csv`
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (err: unknown) {
      alert(getErrorMessage(err, 'Failed to export campaign results'))
    }
  }

  const runScoutLeads = async (campaign: Campaign, approveCreditSpend: boolean) => {
    if (!canManageCampaigns) return
    try {
      setScoutingCampaignId(campaign.id)
      setScoutCandidates(null)
      setPendingScoutApproval(null)
      const res = await authedFetch(orgUrl(`${API_BASE}/api/campaigns/${campaign.id}/scout-leads`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ limit: 50, approve_credit_spend: approveCreditSpend }),
      })
      if (!res.ok) {
        const errData = await res.json().catch(() => null) as { detail?: string | CreditApprovalDetail } | null
        if ((res.status === 428 || res.status === 409) && isCreditApprovalDetail(errData?.detail)) {
          const detail = errData.detail
          setPendingScoutApproval({
            campaign,
            estimatedMaxCredits: detail.estimated_max_credits || 0,
            providerStatuses: detail.provider_statuses || [],
            message: detail.message || 'This run may consume paid provider credits.',
          })
          setScoutingCampaignId(null)
          return
        }
        const detail = typeof errData?.detail === 'string' ? errData.detail : undefined
        throw new Error(detail || 'Scout job failed')
      }
      const data = await res.json() as { result?: ScoutJobResult }
      const result = data.result
      if (!result) {
        throw new Error('Scout job returned an empty response')
      }
      if (result.status === 'FAILED') {
        throw new Error(scoutFailureMessage(result))
      }
      
      const candidates = result.candidates || []
      
      if (candidates.length > 0) {
        setScoutCandidates(candidates)
        setSelectedCandidateIndices(candidates.map((_, i) => i)) // Select all by default
        setScoutingCampaignId(campaign.id) // keep id for import reference
      } else {
        setFeedback({ type: 'success', message: `Scout complete: found ${result.candidates_found || 0} candidates.` })
        setScoutingCampaignId(null)
      }
    } catch (err: unknown) {
      setFeedback({ type: 'error', message: getErrorMessage(err, 'AI Lead Scout failed') })
      setScoutingCampaignId(null)
    }
  }

  const handleScoutLeads = async (campaign: Campaign) => {
    await runScoutLeads(campaign, false)
  }

  const importSelectedCandidates = async () => {
    if (!scoutCandidates || !scoutingCampaignId) return
    const selected = selectedCandidateIndices
      .map(i => scoutCandidates[i])
      .filter((candidate): candidate is ScoutCandidate => Boolean(candidate))
    const importable = selected.filter(candidate => Boolean(candidate.email))
    if (selected.length === 0) {
      setScoutCandidates(null)
      setScoutingCampaignId(null)
      return
    }
    if (importable.length === 0) {
      setFeedback({ type: 'error', message: 'Select at least one reviewed lead with an email before importing.' })
      return
    }
    
    setImportingCandidates(true)
    try {
      const res = await authedFetch(orgUrl(`${API_BASE}/api/leads/import`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          leads: importable,
          campaign_ids: [scoutingCampaignId],
          upsert: true,
          source: 'scout'
        }),
      })
      if (!res.ok) {
        const errData = await res.json().catch(() => null) as { detail?: string } | null
        throw new Error(errData?.detail || 'Import failed')
      }
      
      setFeedback({ type: 'success', message: `✓ Successfully imported ${importable.length} leads.` })
      setScoutCandidates(null)
      setScoutingCampaignId(null)
      await loadCampaigns()
    } catch (err: unknown) {
      setFeedback({ type: 'error', message: getErrorMessage(err, 'Failed to import leads') })
    } finally {
      setImportingCandidates(false)
    }
  }

  if (!isLoaded || !userId) {
    return <div className="flex items-center justify-center min-h-screen">Loading or unauthorized...</div>
  }

  return (
    <AppShell active="campaigns">
      <main className="flex-1 max-w-6xl mx-auto w-full p-8">
        <div className="flex justify-between items-center mb-6">
          <h2 className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">Campaigns</h2>
          <button 
            onClick={openCreateModal}
            disabled={!canManageCampaigns}
            className="px-4 py-2 bg-zinc-900 text-white rounded-md text-sm font-medium hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
          >
            Create Campaign
          </button>
        </div>

        <ActionFeedback feedback={feedback} onDismiss={() => setFeedback(null)} className="mb-6" />
        {error && <div className="p-4 mb-6 text-red-700 bg-red-100 rounded-lg">{error}</div>}

        {loading ? (
          <p className="text-zinc-500">Loading campaigns...</p>
        ) : (
          <div className="bg-white border border-zinc-200 rounded-xl shadow-sm dark:bg-zinc-900 dark:border-zinc-800 overflow-hidden">
            <table className="w-full text-left text-sm">
              <thead className="bg-zinc-50 border-b border-zinc-200 dark:bg-zinc-800 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400">
                <tr>
                  <th className="px-6 py-3 font-medium">Name</th>
                  <th className="px-6 py-3 font-medium">Status</th>
                  <th className="px-6 py-3 font-medium">Assigned Staff</th>
                  <th className="px-6 py-3 font-medium">Approval</th>
                  <th className="px-6 py-3 font-medium">LLM Mode</th>
                  <th className="px-6 py-3 font-medium">Leads Cap</th>
                  <th className="px-6 py-3 font-medium">Delay Days</th>
                  <th className="px-6 py-3 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                {campaigns.map(camp => (
                  <tr key={camp.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/50">
                    <td className="px-6 py-4">
                      <div className="font-medium text-zinc-900 dark:text-zinc-100">{camp.name}</div>
                      <div className="text-xs text-zinc-500 truncate max-w-[200px]">{camp.value_proposition}</div>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${
                        camp.status === 'ACTIVE' ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' :
                        camp.status === 'PAUSED' ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400' :
                        'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-400'
                      }`}>
                        {camp.status}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-zinc-600 dark:text-zinc-400">
                      {camp.staff_names && camp.staff_names.length > 0 ? camp.staff_names.join(', ') : 'No staff assigned'}
                    </td>
                    <td className="px-6 py-4">
                      <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${
                        camp.auto_approve_drafts
                          ? 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300'
                          : 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
                      }`}>
                        Outreach: {camp.auto_approve_drafts ? 'auto-send' : 'review'}
                      </span>
                      <span className={`mt-1 inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${
                        camp.auto_approve_monitor_replies
                          ? 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300'
                          : 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
                      }`}>
                        Replies: {camp.auto_approve_monitor_replies ? 'auto-send' : 'review'}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span className="inline-flex items-center rounded-md bg-zinc-100 px-2 py-1 text-xs font-medium capitalize text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200">
                        {routingModeLabel(camp.llm_routing_mode)}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-zinc-600 dark:text-zinc-400">
                      {camp.max_leads_per_campaign || 'Unlimited'}
                    </td>
                    <td className="px-6 py-4 text-zinc-600 dark:text-zinc-400">
                      {camp.meeting_delay_days}
                    </td>
                    <td className="px-6 py-4 text-right">
                      <button disabled={!canManageCampaigns} onClick={() => openEditModal(camp)} className="text-blue-600 hover:text-blue-800 disabled:opacity-50 dark:text-blue-400 mr-4 font-medium">Edit</button>
                      <button onClick={() => openLeadsModal(camp)} className="text-indigo-600 hover:text-indigo-800 dark:text-indigo-400 mr-4 font-medium">Manage Leads</button>
                      <button onClick={() => openSequenceModal(camp)} className="text-emerald-600 hover:text-emerald-800 dark:text-emerald-400 mr-4 font-medium">Sequence</button>
                      <button
                        disabled={!canManageCampaigns || scoutingCampaignId === camp.id}
                        onClick={() => handleScoutLeads(camp)}
                        className="text-violet-600 hover:text-violet-800 disabled:opacity-50 dark:text-violet-400 mr-4 font-medium"
                        title="Use AI to discover and import new leads based on your campaign value proposition"
                      >
                        {scoutingCampaignId === camp.id ? '⏳ Scouting…' : '✦ Scout Leads'}
                      </button>
                      <button onClick={() => exportCampaignResults(camp)} className="text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100 mr-4 font-medium">Export</button>
                      <button disabled={!canManageCampaigns} onClick={() => handleDelete(camp.id)} className="text-red-600 hover:text-red-800 disabled:opacity-50 dark:text-red-400 font-medium">Delete</button>
                    </td>
                  </tr>
                ))}
                {campaigns.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-6 py-8 text-center text-zinc-500">
                      No campaigns found. Create one to get started.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </main>

      {/* Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 overflow-y-auto">
          <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col">
            <div className="px-6 py-4 border-b border-zinc-200 dark:border-zinc-800 flex justify-between items-center">
              <h3 className="text-lg font-bold text-zinc-900 dark:text-zinc-100">
                {editingCampaign ? 'Edit Campaign' : 'Create Campaign'}
              </h3>
              <button onClick={() => setIsModalOpen(false)} className="text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300">
                &times;
              </button>
            </div>
            
            <form onSubmit={handleSubmit} className="p-6 overflow-y-auto flex-1 space-y-4">
              <ActionFeedback feedback={feedback} onDismiss={() => setFeedback(null)} />
              <div className="grid grid-cols-2 gap-4">
                <div className="col-span-2 sm:col-span-1">
                  <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-1">Name *</label>
                  <input required type="text" value={formData.name} onChange={e => setFormData({...formData, name: e.target.value})} className="w-full px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700" />
                </div>
                
                <div className="col-span-2 sm:col-span-1">
                  <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-1">Status</label>
                  <select value={formData.status} onChange={e => setFormData({...formData, status: e.target.value})} className="w-full px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700">
                    <option value="ACTIVE">ACTIVE</option>
                    <option value="PAUSED">PAUSED</option>
                    <option value="INACTIVE">INACTIVE</option>
                  </select>
                </div>
                
                <div className="col-span-2">
                  <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-1">Value Proposition *</label>
                  <textarea required value={formData.value_proposition} onChange={e => setFormData({...formData, value_proposition: e.target.value})} className="w-full px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700" rows={2} />
                </div>
                
                <div className="col-span-2">
                  <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-1">Call to Action (CTA) *</label>
                  <input required type="text" value={formData.cta} onChange={e => setFormData({...formData, cta: e.target.value})} className="w-full px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700" />
                </div>

                <div className="col-span-2 sm:col-span-1">
                  <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-1">Meeting Delay Days</label>
                  <input type="number" min="0" value={formData.meeting_delay_days} onChange={e => setFormData({...formData, meeting_delay_days: parseInt(e.target.value) || 0})} className="w-full px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700" />
                </div>


                <div className="col-span-2 sm:col-span-1">
                  <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-1">Max Leads Cap (Optional)</label>
                  <input type="number" min="1" placeholder="Unlimited" value={formData.max_leads_per_campaign} onChange={e => setFormData({...formData, max_leads_per_campaign: e.target.value})} className="w-full px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700" />
                </div>

                <div className="col-span-2 sm:col-span-1">
                  <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-1">Lead Selection Order</label>
                  <select value={formData.lead_selection_order} onChange={e => setFormData({...formData, lead_selection_order: e.target.value})} className="w-full px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700">
                    <option value="newest_first">Newest First</option>
                    <option value="oldest_first">Oldest First</option>
                    <option value="random">Random</option>
                    <option value="highest_score">Highest Score (least touched)</option>
                  </select>
                </div>

                <div className="col-span-2">
                  <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-1">LLM Routing Mode</label>
                  <select
                    value={formData.llm_routing_mode}
                    onChange={e => setFormData({...formData, llm_routing_mode: e.target.value})}
                    className="w-full px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700"
                  >
                    <option value="">Use organization/global default</option>
                    <option value="quality_first">Quality first</option>
                    <option value="balanced">Balanced</option>
                    <option value="cost_optimized">Cost optimized</option>
                  </select>
                  <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                    Applies to this campaign&apos;s outbound drafts and monitored inbound reply drafts. Leave as default to follow the platform mode.
                  </p>
                </div>

                <div className="col-span-2 mt-2">
                  <label className="flex items-center gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
                    <input type="checkbox" checked={formData.auto_approve_drafts} onChange={e => setFormData({...formData, auto_approve_drafts: e.target.checked})} className="rounded text-zinc-900 focus:ring-zinc-900" />
                    Send outreach emails without human review
                  </label>
                  <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                    Controls proactive outbound emails created when you run a campaign. When disabled, outreach drafts wait in Draft Approvals.
                  </p>
                </div>

                <div className="col-span-2">
                  <label className="flex items-center gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
                    <input type="checkbox" checked={formData.auto_approve_monitor_replies} onChange={e => setFormData({...formData, auto_approve_monitor_replies: e.target.checked})} className="rounded text-zinc-900 focus:ring-zinc-900" />
                    Send monitored replies without human review
                  </label>
                  <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                    Controls AI replies generated after inbound webhook emails for leads in this campaign. When disabled, reply drafts wait in Draft Approvals.
                  </p>
                </div>
              </div>

              <div className="pt-4 flex justify-end gap-3 border-t border-zinc-200 dark:border-zinc-800 mt-6">
                <button type="button" onClick={() => setIsModalOpen(false)} className="px-4 py-2 border border-zinc-300 rounded-md text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800">
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!canManageCampaigns || campaignSaving}
                  className="px-4 py-2 bg-zinc-900 text-white rounded-md text-sm font-medium hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
                >
                  {campaignSaving ? 'Saving...' : editingCampaign ? 'Save Changes' : 'Create Campaign'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {isLeadsModalOpen && leadCampaign && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 overflow-y-auto">
          <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-xl w-full max-w-3xl max-h-[90vh] flex flex-col">
            <div className="px-6 py-4 border-b border-zinc-200 dark:border-zinc-800 flex justify-between items-center">
              <h3 className="text-lg font-bold text-zinc-900 dark:text-zinc-100">
                Manage Leads - {leadCampaign.name}
              </h3>
              <button onClick={() => setIsLeadsModalOpen(false)} className="text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300">
                &times;
              </button>
            </div>
            <div className="p-6 overflow-y-auto flex-1">
              <p className="text-sm text-zinc-600 dark:text-zinc-400 mb-4">
                Select which leads belong to this campaign. Only selected leads are eligible for outreach.
              </p>
              <div className="space-y-2">
                {campaignLeads.map(lead => (
                  <label key={lead.id} className="flex items-start gap-3 p-3 border rounded-md border-zinc-200 dark:border-zinc-700 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={selectedLeadIds.includes(lead.id)}
                      onChange={() => toggleLeadSelection(lead.id)}
                      className="mt-1"
                    />
                    <div className="text-sm">
                      <div className="font-medium text-zinc-900 dark:text-zinc-100">
                        {lead.name} &lt;{lead.email}&gt;
                      </div>
                      <div className="text-zinc-600 dark:text-zinc-400">
                        {lead.company || 'No company'} | status: {lead.status} | touches: {lead.touch_count} | sent: {lead.emails_sent}
                      </div>
                    </div>
                  </label>
                ))}
                {campaignLeads.length === 0 && (
                  <p className="text-zinc-500 text-sm">No leads found.</p>
                )}
              </div>
            </div>
            <div className="px-6 py-4 border-t border-zinc-200 dark:border-zinc-800 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setIsLeadsModalOpen(false)}
                className="px-4 py-2 border border-zinc-300 rounded-md text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={leadsSaving || !canManageCampaigns}
                onClick={saveLeadAssignments}
                className="px-4 py-2 bg-zinc-900 text-white rounded-md text-sm font-medium hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
              >
                {leadsSaving ? 'Saving...' : 'Save Assignments'}
              </button>
            </div>
          </div>
        </div>
      )}

      {isSequenceModalOpen && sequenceCampaign && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 overflow-y-auto">
          <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col">

            {/* Header */}
            <div className="px-6 py-4 border-b border-zinc-200 dark:border-zinc-800 flex justify-between items-start">
              <div>
                <h3 className="text-lg font-bold text-zinc-900 dark:text-zinc-100">
                  Omnichannel Sequence Builder
                </h3>
                <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">{sequenceCampaign.name}</p>
              </div>
              <button onClick={() => setIsSequenceModalOpen(false)} className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 text-xl leading-none">&times;</button>
            </div>

            {/* Info banner */}
            <div className="mx-6 mt-4 px-4 py-3 rounded-lg bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-200 dark:border-indigo-700 text-xs text-indigo-700 dark:text-indigo-300">
              <strong>How it works:</strong> Each step defines the channel, wait time, and optional AI instructions for the Ghostwriter. The orchestrator advances leads step-by-step. Any reply from a lead immediately halts the sequence.
            </div>

            {/* Steps */}
            <div className="p-6 overflow-y-auto flex-1 space-y-4">

              {sequenceSteps.length === 0 && (
                <div className="flex flex-col items-center justify-center py-10 text-zinc-400 dark:text-zinc-500">
                  <svg className="w-12 h-12 mb-3 opacity-40" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" /></svg>
                  <p className="text-sm font-medium">No steps yet</p>
                  <p className="text-xs mt-1">Click &ldquo;Add Step&rdquo; below to build your cadence.</p>
                </div>
              )}

              {sequenceSteps.map((step, index) => {
                const channelConfig = {
                  email:    { label: '✉️  Email',     color: 'bg-blue-50 border-blue-200 dark:bg-blue-900/20 dark:border-blue-700',    badge: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300' },
                  linkedin: { label: '💼  LinkedIn',  color: 'bg-sky-50 border-sky-200 dark:bg-sky-900/20 dark:border-sky-700',        badge: 'bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300' },
                  whatsapp: { label: '💬  WhatsApp',  color: 'bg-green-50 border-green-200 dark:bg-green-900/20 dark:border-green-700', badge: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300' },
                }[step.channel] ?? { label: '✉️  Email', color: 'bg-blue-50 border-blue-200 dark:bg-blue-900/20 dark:border-blue-700', badge: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300' }

                return (
                  <div key={`${step.id || 'new'}-${index}`} className={`border rounded-xl p-5 space-y-4 transition-colors ${channelConfig.color}`}>

                    {/* Step header row */}
                    <div className="flex items-center gap-3 flex-wrap">
                      <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${channelConfig.badge}`}>
                        Step {step.step_number}
                      </span>
                      <span className="text-xs text-zinc-500 dark:text-zinc-400">→ wait {step.delay_days} day{step.delay_days !== 1 ? 's' : ''} → send via</span>
                      <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${channelConfig.badge}`}>
                        {channelConfig.label}
                      </span>
                      <div className="ml-auto flex items-center gap-2">
                        <label className="flex items-center gap-1.5 text-xs text-zinc-600 dark:text-zinc-400 cursor-pointer">
                          <input type="checkbox" checked={!!step.active} onChange={(e) => updateSequenceStep(index, { active: e.target.checked })} className="rounded" />
                          Active
                        </label>
                        <button
                          type="button"
                          onClick={() => setSequenceSteps(current => current.filter((_, i) => i !== index))}
                          className="text-xs text-rose-500 hover:text-rose-700 dark:text-rose-400 font-medium px-2 py-1 rounded hover:bg-rose-50 dark:hover:bg-rose-900/20 transition-colors"
                        >
                          Remove
                        </button>
                      </div>
                    </div>

                    {/* Config row */}
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                      <div>
                        <label className="block text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-1">Step #</label>
                        <input
                          type="number" min="1"
                          value={step.step_number}
                          onChange={(e) => updateSequenceStep(index, { step_number: parseInt(e.target.value) || 1 })}
                          className="w-full px-3 py-2 border rounded-lg text-sm bg-white dark:bg-zinc-800 border-zinc-300 dark:border-zinc-700"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-1">Wait (days after previous touch)</label>
                        <input
                          type="number" min="1"
                          value={step.delay_days}
                          onChange={(e) => updateSequenceStep(index, { delay_days: parseInt(e.target.value) || 1 })}
                          className="w-full px-3 py-2 border rounded-lg text-sm bg-white dark:bg-zinc-800 border-zinc-300 dark:border-zinc-700"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-1">Channel</label>
                        <select
                          value={step.channel}
                          onChange={(e) => updateSequenceStep(index, { channel: e.target.value as 'email' | 'linkedin' | 'whatsapp' })}
                          className="w-full px-3 py-2 border rounded-lg text-sm bg-white dark:bg-zinc-800 border-zinc-300 dark:border-zinc-700"
                        >
                          <option value="email">✉️  Email</option>
                          <option value="linkedin">💼  LinkedIn</option>
                          <option value="whatsapp">💬  WhatsApp</option>
                        </select>
                      </div>
                    </div>

                    {/* AI prompt context */}
                    <div>
                      <label className="block text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-1">
                        AI Ghostwriter Instructions <span className="font-normal text-zinc-400">(optional – guides the AI for this specific step)</span>
                      </label>
                      <textarea
                        rows={2}
                        placeholder={`e.g. "Reference our previous email. Ask a yes/no qualifying question about their current pipeline tool."${step.channel === 'linkedin' ? ' Max 300 chars.' : ''}`}
                        value={step.prompt_context}
                        onChange={(e) => updateSequenceStep(index, { prompt_context: e.target.value })}
                        className="w-full px-3 py-2 border rounded-lg text-sm bg-white dark:bg-zinc-800 border-zinc-300 dark:border-zinc-700 resize-none"
                      />
                    </div>

                    {/* Email-only template fields */}
                    {step.channel === 'email' && (
                      <>
                        <div>
                          <label className="block text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-1">Subject template</label>
                          <input
                            type="text"
                            value={step.subject_template}
                            onChange={(e) => updateSequenceStep(index, { subject_template: e.target.value })}
                            className="w-full px-3 py-2 border rounded-lg text-sm bg-white dark:bg-zinc-800 border-zinc-300 dark:border-zinc-700"
                            placeholder="Re: {campaign_name}"
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-1">
                            Body template <span className="font-normal text-zinc-400">(supports <code>{'{name}'}</code>, <code>{'{value_proposition}'}</code>, <code>{'{cta}'}</code>, <code>{'{sender_name}'}</code>)</span>
                          </label>
                          <textarea
                            rows={5}
                            value={step.body_template}
                            onChange={(e) => updateSequenceStep(index, { body_template: e.target.value })}
                            className="w-full px-3 py-2 border rounded-lg text-sm bg-white dark:bg-zinc-800 border-zinc-300 dark:border-zinc-700 resize-y"
                          />
                        </div>
                      </>
                    )}

                    {/* Non-email hint */}
                    {step.channel !== 'email' && (
                      <div className="text-xs text-zinc-500 dark:text-zinc-400 italic">
                        {step.channel === 'linkedin'
                          ? '💼 The AI will draft a LinkedIn connection note (≤300 chars). Your SDR sends it manually via the Draft Approvals queue.'
                          : '💬 The AI will draft a WhatsApp message. Your SDR sends it manually via the Draft Approvals queue. A wa.me deep-link will be generated.'}
                      </div>
                    )}
                  </div>
                )
              })}

              <button
                type="button"
                onClick={addSequenceStep}
                className="w-full py-3 border-2 border-dashed border-zinc-300 dark:border-zinc-700 rounded-xl text-sm font-medium text-zinc-500 dark:text-zinc-400 hover:border-indigo-400 hover:text-indigo-600 dark:hover:border-indigo-500 dark:hover:text-indigo-400 transition-colors"
              >
                + Add Step
              </button>
            </div>

            {/* Footer */}
            <div className="px-6 py-4 border-t border-zinc-200 dark:border-zinc-800 flex flex-col gap-3">
              {/* Inline feedback — always visible above the buttons */}
              {sequenceFeedback && (
                <div className={`flex items-start gap-2 rounded-lg px-4 py-3 text-sm font-medium ${
                  sequenceFeedback.type === 'success'
                    ? 'bg-emerald-50 text-emerald-800 border border-emerald-200 dark:bg-emerald-900/20 dark:text-emerald-300 dark:border-emerald-700'
                    : 'bg-red-50 text-red-800 border border-red-200 dark:bg-red-900/20 dark:text-red-300 dark:border-red-700'
                }`}>
                  <span className="mt-0.5 shrink-0">{sequenceFeedback.type === 'success' ? '✓' : '✕'}</span>
                  <span className="flex-1">{sequenceFeedback.message}</span>
                  <button onClick={() => setSequenceFeedback(null)} className="shrink-0 opacity-60 hover:opacity-100">&times;</button>
                </div>
              )}
              <div className="flex justify-between items-center gap-3">
                <span className="text-xs text-zinc-400 dark:text-zinc-500">
                  {sequenceSteps.length} step{sequenceSteps.length !== 1 ? 's' : ''} &middot; Exit criteria: any lead reply halts the sequence automatically.
                </span>
                <div className="flex gap-3">
                  <button
                    type="button"
                    onClick={() => setIsSequenceModalOpen(false)}
                    className="px-4 py-2 border border-zinc-300 rounded-lg text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    disabled={sequenceSaving || !canManageCampaigns}
                    onClick={saveSequence}
                    className="px-5 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors flex items-center gap-2"
                  >
                    {sequenceSaving && (
                      <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                      </svg>
                    )}
                    {sequenceSaving ? 'Saving...' : 'Save Sequence'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {pendingScoutApproval && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex min-h-screen items-center justify-center px-4 py-8 text-center">
            <div className="fixed inset-0 bg-zinc-900/50 backdrop-blur-sm" onClick={() => setPendingScoutApproval(null)} />
            <div className="relative w-full max-w-lg rounded-xl border border-zinc-200 bg-white p-6 text-left shadow-xl dark:border-zinc-800 dark:bg-zinc-900">
              <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Approve paid lead discovery</h3>
              <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">{pendingScoutApproval.message}</p>
              <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-100">
                Estimated maximum: {pendingScoutApproval.estimatedMaxCredits} provider credit{pendingScoutApproval.estimatedMaxCredits === 1 ? '' : 's'}
              </div>
              {pendingScoutApproval.providerStatuses.length > 0 && (
                <div className="mt-4 space-y-2">
                  {pendingScoutApproval.providerStatuses.map(provider => (
                    <div key={`${provider.name}-${provider.status}-${provider.reason || ''}`} className="flex items-start justify-between gap-4 rounded-md border border-zinc-200 px-3 py-2 text-sm dark:border-zinc-800">
                      <div>
                        <div className="font-medium text-zinc-900 dark:text-zinc-100">{provider.name}</div>
                        {provider.message && <div className="text-xs text-zinc-500 dark:text-zinc-400">{provider.message}</div>}
                      </div>
                      <span className="shrink-0 rounded-md bg-zinc-100 px-2 py-1 text-xs font-medium text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200">
                        {provider.reason || provider.status}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-6 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setPendingScoutApproval(null)}
                  className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={scoutingCampaignId === pendingScoutApproval.campaign.id}
                  onClick={() => runScoutLeads(pendingScoutApproval.campaign, true)}
                  className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
                >
                  {scoutingCampaignId === pendingScoutApproval.campaign.id ? 'Starting...' : 'Approve and scout'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Scout Candidates Review Modal */}
      {scoutCandidates && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex items-center justify-center min-h-screen px-4 pt-4 pb-20 text-center sm:p-0">
            <div className="fixed inset-0 transition-opacity bg-zinc-900/50 backdrop-blur-sm" onClick={() => setScoutCandidates(null)} />
            <div className="relative inline-block w-full max-w-4xl p-6 overflow-hidden text-left align-middle transition-all transform bg-white shadow-xl rounded-2xl dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800">
              <div className="flex items-center justify-between mb-5">
                <div>
                  <h3 className="text-xl font-bold text-zinc-900 dark:text-zinc-50">Review Scouted Leads</h3>
                  <p className="text-sm text-zinc-500 mt-1">Select the leads you want to import into your campaign.</p>
                </div>
                <button onClick={() => setScoutCandidates(null)} className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 text-xl leading-none">&times;</button>
              </div>

              {hasMockScoutCandidates && (
                <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-100">
                  Demo data: some candidates came from MockDiscoverer because real lead providers were unavailable. Do not use these contacts for real outreach.
                </div>
              )}

              <div className="max-h-[60vh] overflow-y-auto pr-2 custom-scrollbar">
                <table className="w-full text-left text-sm">
                  <thead className="bg-zinc-50 border-b border-zinc-200 dark:bg-zinc-800 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400 sticky top-0 z-10">
                    <tr>
                      <th className="px-4 py-3 font-medium w-12 text-center">
                        <input
                          type="checkbox"
                          checked={selectedCandidateIndices.length === scoutCandidates.length && scoutCandidates.length > 0}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setSelectedCandidateIndices(scoutCandidates.map((_, i) => i))
                            } else {
                              setSelectedCandidateIndices([])
                            }
                          }}
                          className="rounded border-zinc-300 text-indigo-600 focus:ring-indigo-500 dark:border-zinc-600 dark:bg-zinc-700"
                        />
                      </th>
                      <th className="px-4 py-3 font-medium">Name</th>
                      <th className="px-4 py-3 font-medium">Title & Company</th>
                      <th className="px-4 py-3 font-medium">Location</th>
                      <th className="px-4 py-3 font-medium">Email</th>
                      <th className="px-4 py-3 font-medium">Source</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                    {scoutCandidates.map((candidate, idx) => (
                      <tr key={idx} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/50">
                        <td className="px-4 py-3 text-center">
                          <input
                            type="checkbox"
                            checked={selectedCandidateIndices.includes(idx)}
                            onChange={() => {
                              setSelectedCandidateIndices(prev => 
                                prev.includes(idx) ? prev.filter(i => i !== idx) : [...prev, idx]
                              )
                            }}
                            className="rounded border-zinc-300 text-indigo-600 focus:ring-indigo-500 dark:border-zinc-600 dark:bg-zinc-700"
                          />
                        </td>
                        <td className="px-4 py-3 font-medium text-zinc-900 dark:text-zinc-100">{candidate.name}</td>
                        <td className="px-4 py-3">
                          <div className="text-zinc-900 dark:text-zinc-100">{candidate.job_title}</div>
                          <div className="text-xs text-zinc-500">{candidate.company}</div>
                        </td>
                        <td className="px-4 py-3 text-zinc-600 dark:text-zinc-400">{candidate.location}</td>
                        <td className="px-4 py-3 text-zinc-600 dark:text-zinc-400">{candidate.email}</td>
                        <td className="px-4 py-3">
                          <span className={`inline-flex rounded-md px-2 py-1 text-xs font-medium ${
                            isMockCandidate(candidate)
                              ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200'
                              : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200'
                          }`}>
                            {isMockCandidate(candidate) ? 'Demo mock' : candidate.enrichment_source || 'Provider'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="mt-6 flex justify-between items-center pt-5 border-t border-zinc-200 dark:border-zinc-800">
                <div className="text-sm text-zinc-500 font-medium">
                  {selectedCandidateIndices.length} of {scoutCandidates.length} selected
                </div>
                <div className="flex gap-3">
                  <button
                    type="button"
                    onClick={() => setScoutCandidates(null)}
                    className="px-4 py-2 border border-zinc-300 rounded-lg text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    disabled={importingCandidates || selectedCandidateIndices.length === 0}
                    onClick={importSelectedCandidates}
                    className="px-5 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors flex items-center gap-2"
                  >
                    {importingCandidates && (
                      <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                      </svg>
                    )}
                    {importingCandidates
                      ? 'Importing...'
                      : hasMockScoutCandidates
                        ? 'Import Selected Demo Leads'
                        : 'Import Selected'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  )
}
