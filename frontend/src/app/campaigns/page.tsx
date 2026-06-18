'use client'

import { useCallback, useEffect, useState } from 'react'
import { useAuth } from "@clerk/clerk-react";
import { AppShell } from '@/components/app-shell'
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

interface StaffAssignment {
  name: string
  assigned: boolean | number
}

interface SequenceStep {
  id?: number
  step_number: number
  delay_days: number
  subject_template: string
  body_template: string
  active: boolean | number
}

function getErrorMessage(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback
}

export default function CampaignsPage() {
  const { isLoaded, userId, getToken } = useAuth()
  const { selectedOrganizationId, selectedOrganization, orgUrl } = useTenantScope()
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

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
    max_emails_per_lead: 5
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
      const baseCampaigns: Campaign[] = data.campaigns || []

      const campaignsWithStaff = await Promise.all(
        baseCampaigns.map(async (campaign) => {
          try {
            const staffRes = await authedFetch(orgUrl(`${API_BASE}/api/campaigns/${campaign.id}/staff`))
            if (!staffRes.ok) {
              return { ...campaign, staff_names: [] }
            }
            const staffData = await staffRes.json() as { staff?: StaffAssignment[] }
            const assignedNames = (staffData.staff || [])
              .filter((s) => !!s.assigned)
              .map((s) => s.name)
            return { ...campaign, staff_names: assignedNames }
          } catch {
            return { ...campaign, staff_names: [] }
          }
        })
      )

      setCampaigns(campaignsWithStaff)
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to fetch campaigns'))
    } finally {
      setLoading(false)
    }
  }, [getToken, orgUrl, selectedOrganizationId])

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
      const res = await authedFetch(orgUrl(`${API_BASE}/api/campaigns/${id}`), {
        method: 'DELETE',
      })
      if (!res.ok) throw new Error('Failed to delete')
      setCampaigns(campaigns.filter(c => c.id !== id))
    } catch (err: unknown) {
      alert(getErrorMessage(err, 'Failed to delete'))
    }
  }

  const openCreateModal = () => {
    if (!canManageCampaigns) return
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
      max_emails_per_lead: 5
    })
    setIsModalOpen(true)
  }

  const openEditModal = (campaign: Campaign) => {
    if (!canManageCampaigns) return
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
      max_emails_per_lead: campaign.max_emails_per_lead
    })
    setIsModalOpen(true)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canManageCampaigns) return
    try {
      const payload = {
        ...formData,
        max_leads_per_campaign: formData.max_leads_per_campaign ? parseInt(formData.max_leads_per_campaign) : null,
        meeting_delay_days: formData.meeting_delay_days,
        max_emails_per_lead: formData.max_emails_per_lead
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
      
      await loadCampaigns()
      setIsModalOpen(false)
    } catch (err: unknown) {
      alert(getErrorMessage(err, 'Failed to save campaign'))
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
    } catch (err: unknown) {
      alert(getErrorMessage(err, 'Failed to save lead assignments'))
    } finally {
      setLeadsSaving(false)
    }
  }

  const openSequenceModal = async (campaign: Campaign) => {
    try {
      setSequenceCampaign(campaign)
      setIsSequenceModalOpen(true)
      const res = await authedFetch(orgUrl(`${API_BASE}/api/campaigns/${campaign.id}/sequence`))
      if (!res.ok) throw new Error('Failed to load follow-up sequence')
      const data = await res.json() as { steps?: SequenceStep[] }
      setSequenceSteps((data.steps || []).map(step => ({ ...step, active: !!step.active })))
    } catch (err: unknown) {
      alert(getErrorMessage(err, 'Failed to load follow-up sequence'))
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
      subject_template: 'Re: {campaign_name}',
      body_template: 'Hi {name},\n\nFollowing up on my previous note about {value_proposition}.\n\n{cta}\n\nBest,\n{sender_name}',
      active: true,
    }])
  }

  const saveSequence = async () => {
    if (!sequenceCampaign || !canManageCampaigns) return
    try {
      setSequenceSaving(true)
      const res = await authedFetch(orgUrl(`${API_BASE}/api/campaigns/${sequenceCampaign.id}/sequence`), {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ steps: sequenceSteps.map(step => ({ ...step, active: !!step.active })) })
      })
      if (!res.ok) throw new Error('Failed to save follow-up sequence')
      setIsSequenceModalOpen(false)
    } catch (err: unknown) {
      alert(getErrorMessage(err, 'Failed to save follow-up sequence'))
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
                      <button onClick={() => exportCampaignResults(camp)} className="text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100 mr-4 font-medium">Export</button>
                      <button disabled={!canManageCampaigns} onClick={() => handleDelete(camp.id)} className="text-red-600 hover:text-red-800 disabled:opacity-50 dark:text-red-400 font-medium">Delete</button>
                    </td>
                  </tr>
                ))}
                {campaigns.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-6 py-8 text-center text-zinc-500">
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
                  <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-1">Max Emails Per Lead</label>
                  <input type="number" min="1" value={formData.max_emails_per_lead} onChange={e => setFormData({...formData, max_emails_per_lead: parseInt(e.target.value) || 1})} className="w-full px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700" />
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
                <button type="submit" disabled={!canManageCampaigns} className="px-4 py-2 bg-zinc-900 text-white rounded-md text-sm font-medium hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200">
                  {editingCampaign ? 'Save Changes' : 'Create Campaign'}
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
          <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-xl w-full max-w-4xl max-h-[90vh] flex flex-col">
            <div className="px-6 py-4 border-b border-zinc-200 dark:border-zinc-800 flex justify-between items-center">
              <h3 className="text-lg font-bold text-zinc-900 dark:text-zinc-100">
                Follow-up Sequence - {sequenceCampaign.name}
              </h3>
              <button onClick={() => setIsSequenceModalOpen(false)} className="text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300">
                &times;
              </button>
            </div>
            <div className="p-6 overflow-y-auto flex-1 space-y-4">
              {sequenceSteps.map((step, index) => (
                <div key={`${step.id || 'new'}-${index}`} className="border border-zinc-200 dark:border-zinc-700 rounded-lg p-4 space-y-3">
                  <div className="grid grid-cols-1 md:grid-cols-[120px_140px_minmax(0,1fr)_90px] gap-3">
                    <input
                      type="number"
                      min="1"
                      value={step.step_number}
                      onChange={(e) => updateSequenceStep(index, { step_number: parseInt(e.target.value) || 1 })}
                      className="px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700"
                    />
                    <input
                      type="number"
                      min="1"
                      value={step.delay_days}
                      onChange={(e) => updateSequenceStep(index, { delay_days: parseInt(e.target.value) || 1 })}
                      className="px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700"
                    />
                    <input
                      type="text"
                      value={step.subject_template}
                      onChange={(e) => updateSequenceStep(index, { subject_template: e.target.value })}
                      className="px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700"
                    />
                    <label className="flex items-center gap-2 text-sm">
                      <input type="checkbox" checked={!!step.active} onChange={(e) => updateSequenceStep(index, { active: e.target.checked })} />
                      Active
                    </label>
                  </div>
                  <textarea
                    rows={5}
                    value={step.body_template}
                    onChange={(e) => updateSequenceStep(index, { body_template: e.target.value })}
                    className="w-full px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700"
                  />
                  <button
                    type="button"
                    onClick={() => setSequenceSteps(current => current.filter((_, i) => i !== index))}
                    className="text-sm text-rose-600 dark:text-rose-400"
                  >
                    Remove step
                  </button>
                </div>
              ))}
              {sequenceSteps.length === 0 && <p className="text-sm text-zinc-500">No follow-up steps configured.</p>}
              <button
                type="button"
                onClick={addSequenceStep}
                className="px-3 py-2 border border-zinc-300 rounded-md text-sm font-medium dark:border-zinc-700"
              >
                Add Step
              </button>
            </div>
            <div className="px-6 py-4 border-t border-zinc-200 dark:border-zinc-800 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setIsSequenceModalOpen(false)}
                className="px-4 py-2 border border-zinc-300 rounded-md text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={sequenceSaving || !canManageCampaigns}
                onClick={saveSequence}
                className="px-4 py-2 bg-zinc-900 text-white rounded-md text-sm font-medium hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
              >
                {sequenceSaving ? 'Saving...' : 'Save Sequence'}
              </button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  )
}
