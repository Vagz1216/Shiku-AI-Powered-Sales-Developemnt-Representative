'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { SignInButton, useAuth } from "@clerk/clerk-react";
import Link from 'next/link'
import { AppShell } from '@/components/app-shell'
import { useTenantScope } from '@/components/tenant-scope'
import { fetchWithAuthRetry } from '@/lib/auth-fetch'
import { DEFAULT_TIME_ZONE, TIME_ZONE_OPTIONS, formatTime, formatTimestamp, normalizeTimeZone, toDatetimeLocal, zonedLocalToIso } from '@/lib/time'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Campaign {
  id: number
  name: string
  value_proposition: string
  cta: string
  status: string
  auto_approve_drafts: boolean
  auto_approve_monitor_replies: boolean
}

interface LogEntry {
  status: string
  message: string
  event_id?: string
  organization_id?: number | null
  timestamp?: string
}

interface AnalyticsSummary {
  totals: {
    leads: number
    active_campaigns: number
    pending_drafts: number
    scheduled_emails: number
    sent_emails: number
    inbound_replies: number
    meetings_booked: number
    opted_out: number
  }
  rates: {
    reply_rate: number
    meeting_rate: number
    opt_out_rate: number
  }
}

interface ScheduledEmail {
  id: number
  subject: string
  body: string
  scheduled_send_at: string
  created_at: string
  send_attempts: number
  last_error: string | null
  lead_name: string | null
  lead_email: string
  campaign_name: string
}

interface UpcomingFollowup {
  campaign_id: number
  campaign_name: string
  lead_id: number
  email: string
  name: string | null
  company: string | null
  status: string
  last_contacted_at: string | null
  step_number: number
  delay_days: number
  due_at: string | null
  is_due: boolean
  blocked_reason: string | null
  existing_message_id?: number
  existing_message_status?: string
}

export default function Home() {
  const { isLoaded, userId, getToken } = useAuth()
  const {
    selectedOrganizationId: tenantSelectedOrganizationId,
    selectedOrganization: tenantSelectedOrganization,
    reloadOrganizations,
    orgUrl,
  } = useTenantScope()
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [organizationTimezone, setOrganizationTimezone] = useState(DEFAULT_TIME_ZONE)
  const [selectedCampaign, setSelectedCampaign] = useState<string>('')
  const [pendingDraftCount, setPendingDraftCount] = useState<number>(0)
  const [analytics, setAnalytics] = useState<AnalyticsSummary | null>(null)
  
  // State for logs
  const [activeTab, setActiveTab] = useState<'outreach' | 'monitor'>('outreach')
  const [outreachLogs, setOutreachLogs] = useState<LogEntry[]>([])
  const [monitorLogs, setMonitorLogs] = useState<LogEntry[]>([])
  
  const [isStreaming, setIsStreaming] = useState(false)
  const [isMonitoring, setIsMonitoring] = useState(false)
  const [scheduledOpen, setScheduledOpen] = useState(false)
  const [scheduledEmails, setScheduledEmails] = useState<ScheduledEmail[]>([])
  const [scheduledLoading, setScheduledLoading] = useState(false)
  const [editingScheduled, setEditingScheduled] = useState<ScheduledEmail | null>(null)
  const [scheduledSubject, setScheduledSubject] = useState('')
  const [scheduledBody, setScheduledBody] = useState('')
  const [scheduledTime, setScheduledTime] = useState('')
  const [followupsOpen, setFollowupsOpen] = useState(false)
  const [upcomingFollowups, setUpcomingFollowups] = useState<UpcomingFollowup[]>([])
  const [followupsLoading, setFollowupsLoading] = useState(false)

  const effectiveOrganizationId = tenantSelectedOrganizationId
  const selectedOrganization = tenantSelectedOrganization
  const canEditOrganizationTimezone = !!selectedOrganization?.capabilities?.can_manage_organization
  const hasActiveSubscription = !!selectedOrganization?.subscription?.is_active
  const isPlatformManagementContext = selectedOrganization?.current_user_role === 'system_owner'
    && !selectedOrganization?.capabilities?.can_run_outreach
  const canRunOutreach = !!selectedOrganization?.capabilities?.can_run_outreach && hasActiveSubscription
  const visibleMonitorLogs = useMemo(
    () => monitorLogs.filter(log => !log.organization_id || log.organization_id === effectiveOrganizationId),
    [monitorLogs, effectiveOrganizationId],
  )

  const authedFetch = useCallback((url: string, init: RequestInit = {}) => {
    return fetchWithAuthRetry(getToken, url, init)
  }, [getToken])

  useEffect(() => {
    if (selectedOrganization?.timezone) {
      const timer = window.setTimeout(() => {
        setOrganizationTimezone(normalizeTimeZone(selectedOrganization.timezone))
      }, 0)
      return () => window.clearTimeout(timer)
    }
  }, [selectedOrganization?.timezone])

  const withLogTimestamp = (entry: LogEntry): LogEntry => ({
    ...entry,
    timestamp: entry.timestamp || new Date().toISOString(),
  })

  // Start Email Monitor SSE connection
  useEffect(() => {
    if (!isLoaded || !userId || activeTab !== 'monitor' || !effectiveOrganizationId) return

    let eventSource: EventSource | null = null
    let cancelled = false

    const connectMonitor = async () => {
      try {
        const token = await getToken({ skipCache: true })
        if (!token || cancelled) return

        const url = new URL(`${API_BASE}/api/webhooks/stream`)
        url.searchParams.append('token', token)
        url.searchParams.append('organization_id', String(effectiveOrganizationId))

        eventSource = new EventSource(url.toString())
        setIsMonitoring(true)

        eventSource.onmessage = (event) => {
          const data = JSON.parse(event.data) as LogEntry
          setMonitorLogs(prev => [...prev, withLogTimestamp(data)])
        }

        eventSource.onerror = (err) => {
          console.error('Monitor EventSource failed:', err)
          setIsMonitoring(false)
          eventSource?.close()
        }
      } catch (err) {
        console.error('Failed to connect to monitor:', err)
      }
    }

    void connectMonitor()

    return () => {
      cancelled = true
      eventSource?.close()
      setIsMonitoring(false)
    }
  }, [isLoaded, userId, activeTab, getToken, effectiveOrganizationId])

  useEffect(() => {
    if (isLoaded && userId) {
      const loadCampaigns = async () => {
        try {
          if (!effectiveOrganizationId) return
          const res = await authedFetch(orgUrl(`${API_BASE}/api/campaigns`))
          const data = await res.json()
          setCampaigns(data.campaigns || [])
        } catch (err) {
          console.error('Error fetching campaigns:', err)
        }
      }
      const loadDraftCount = async () => {
        try {
          if (!effectiveOrganizationId) return
          const res = await authedFetch(orgUrl(`${API_BASE}/api/drafts/count`))
          if (!res.ok) return
          const data = await res.json()
          setPendingDraftCount(Number(data.count || 0))
        } catch (err) {
          console.error('Error fetching draft count:', err)
        }
      }
      const loadAnalytics = async () => {
        try {
          if (!effectiveOrganizationId) return
          const res = await authedFetch(orgUrl(`${API_BASE}/api/analytics/summary`))
          if (!res.ok) return
          setAnalytics(await res.json())
        } catch (err) {
          console.error('Error fetching analytics:', err)
        }
      }
      loadCampaigns()
      loadDraftCount()
      loadAnalytics()
    }
  }, [isLoaded, userId, getToken, effectiveOrganizationId, orgUrl, authedFetch])

  const refreshPendingDraftCount = async () => {
    try {
      const res = await authedFetch(orgUrl(`${API_BASE}/api/drafts/count`))
      if (!res.ok) return
      const data = await res.json()
      setPendingDraftCount(Number(data.count || 0))
    } catch (err) {
      console.error('Error fetching draft count:', err)
    }
  }

  const selectedCampaignId = () => {
    return selectedCampaign ? campaigns.find(camp => camp.name === selectedCampaign)?.id || null : null
  }

  const saveOrganizationTimezone = async (timezone: string) => {
    const nextTimezone = normalizeTimeZone(timezone)
    setOrganizationTimezone(nextTimezone)
    if (!effectiveOrganizationId || !canEditOrganizationTimezone) return
    try {
      const res = await authedFetch(`${API_BASE}/api/organizations/${effectiveOrganizationId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ timezone: nextTimezone }),
      })
      if (!res.ok) throw new Error('Failed to update organization timezone')
      await reloadOrganizations()
    } catch (err) {
      console.error('Failed to update organization timezone:', err)
    }
  }

  const loadScheduledEmails = async () => {
    try {
      setScheduledLoading(true)
      const res = await authedFetch(orgUrl(`${API_BASE}/api/scheduled-emails?limit=100`))
      if (!res.ok) throw new Error('Failed to load scheduled emails')
      const data = await res.json() as { scheduled?: ScheduledEmail[] }
      setScheduledEmails(data.scheduled || [])
    } catch (err) {
      console.error('Failed to load scheduled emails:', err)
    } finally {
      setScheduledLoading(false)
    }
  }

  const openScheduledQueue = async () => {
    setScheduledOpen(true)
    await loadScheduledEmails()
  }

  const startEditScheduled = (email: ScheduledEmail) => {
    setEditingScheduled(email)
    setScheduledSubject(email.subject)
    setScheduledBody(email.body)
    setScheduledTime(toDatetimeLocal(email.scheduled_send_at, organizationTimezone))
  }

  const saveScheduledEdit = async () => {
    if (!editingScheduled || !scheduledTime.trim() || !canRunOutreach) return
    try {
      const res = await authedFetch(orgUrl(`${API_BASE}/api/scheduled-emails/${editingScheduled.id}`), {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          subject: scheduledSubject,
          body: scheduledBody,
          scheduled_send_at: zonedLocalToIso(scheduledTime, organizationTimezone),
        }),
      })
      if (!res.ok) throw new Error('Failed to update scheduled email')
      setEditingScheduled(null)
      await loadScheduledEmails()
    } catch (err) {
      console.error('Failed to update scheduled email:', err)
    }
  }

  const returnScheduledToReview = async (email: ScheduledEmail) => {
    if (!canRunOutreach) return
    if (!confirm(`Return scheduled email #${email.id} to Draft Approvals?`)) return
    try {
      const res = await authedFetch(orgUrl(`${API_BASE}/api/scheduled-emails/${email.id}/return-to-review`), {
        method: 'POST',
      })
      if (!res.ok) throw new Error('Failed to return scheduled email to review')
      await loadScheduledEmails()
      await refreshPendingDraftCount()
    } catch (err) {
      console.error('Failed to return scheduled email:', err)
    }
  }

  const loadUpcomingFollowups = async () => {
    try {
      setFollowupsLoading(true)
      const campaignId = selectedCampaignId()
      const url = new URL(`${API_BASE}/api/followups/upcoming`)
      if (effectiveOrganizationId) url.searchParams.set('organization_id', String(effectiveOrganizationId))
      url.searchParams.set('limit', '100')
      if (campaignId) url.searchParams.set('campaign_id', String(campaignId))
      const res = await authedFetch(url.toString())
      if (!res.ok) throw new Error('Failed to load upcoming follow-ups')
      const data = await res.json() as { followups?: UpcomingFollowup[] }
      setUpcomingFollowups(data.followups || [])
    } catch (err) {
      console.error('Failed to load upcoming follow-ups:', err)
    } finally {
      setFollowupsLoading(false)
    }
  }

  const openFollowupQueue = async () => {
    setFollowupsOpen(true)
    await loadUpcomingFollowups()
  }

  const startOutreach = async () => {
    if (!canRunOutreach) return
    setOutreachLogs([])
    setIsStreaming(true)
    setActiveTab('outreach')
    
    try {
      const token = await getToken({ skipCache: true })
      const url = new URL(`${API_BASE}/api/outreach/stream`)
      if (effectiveOrganizationId) url.searchParams.set('organization_id', String(effectiveOrganizationId))
      if (selectedCampaign) {
        url.searchParams.append('campaign_name', selectedCampaign)
      }
      if (token) {
        url.searchParams.append('token', token)
      }

      const eventSource = new EventSource(url.toString())

      eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data)
        setOutreachLogs(prev => [...prev, withLogTimestamp(data)])
        
        if (data.status === 'success' || data.status === 'error') {
          eventSource.close()
          setIsStreaming(false)
          void refreshPendingDraftCount()
        }
      }

      eventSource.onerror = (err) => {
        console.error('EventSource failed:', err)
        setOutreachLogs(prev => [...prev, withLogTimestamp({ status: 'error', message: 'Connection to server lost or unauthorized' })])
        eventSource.close()
        setIsStreaming(false)
      }
    } catch (err) {
      console.error('Failed to start outreach:', err)
      setIsStreaming(false)
    }
  }

  const runScheduledSends = async () => {
    if (!canRunOutreach) return
    try {
      const res = await authedFetch(orgUrl(`${API_BASE}/api/scheduled-emails/send-due`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ limit: 50 }),
      })
      const data = await res.json()
      setOutreachLogs(prev => [...prev, withLogTimestamp({
        status: res.ok ? 'success' : 'error',
        message: res.ok ? `Scheduled sender processed ${data.processed || 0}; sent ${data.sent || 0}.` : (data.detail || 'Scheduled send failed')
      })])
      void refreshPendingDraftCount()
      void loadScheduledEmails()
    } catch (err) {
      console.error('Failed to send due scheduled emails:', err)
    }
  }

  const generateFollowups = async () => {
    if (!canRunOutreach) return
    try {
      const campaignId = selectedCampaignId()
      const res = await authedFetch(orgUrl(`${API_BASE}/api/followups/generate-due`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ campaign_id: campaignId, limit: 50 }),
      })
      const data = await res.json()
      setOutreachLogs(prev => [...prev, withLogTimestamp({
        status: res.ok ? 'success' : 'error',
        message: res.ok ? `Generated ${data.generated || 0} follow-up draft(s).` : (data.detail || 'Follow-up generation failed')
      })])
      void refreshPendingDraftCount()
      void loadUpcomingFollowups()
    } catch (err) {
      console.error('Failed to generate follow-ups:', err)
    }
  }

  const selectedCampaignDetails = selectedCampaign
    ? campaigns.find(camp => camp.name === selectedCampaign)
    : null

  if (!isLoaded) {
    return <div className="flex items-center justify-center min-h-screen">Loading...</div>
  }

  if (!userId) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-zinc-50 p-6 text-center dark:bg-zinc-950">
        <div className="max-w-xl">
          <h1 className="mb-4 text-4xl font-extrabold text-zinc-900 dark:text-zinc-50">
            Enterprise SDR AI
          </h1>
          <p className="mb-8 text-lg text-zinc-600 dark:text-zinc-400">
            Automate outbound sales with reviewable AI drafts, scheduled sends, follow-ups, and compliance visibility.
          </p>
          <SignInButton mode="modal">
            <button className="rounded-md bg-zinc-900 px-6 py-3 text-sm font-semibold text-white hover:bg-zinc-800 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200">
              Sign In
            </button>
          </SignInButton>
        </div>
      </div>
    )
  }

  return (
    <AppShell active="dashboard">
      <main className="mx-auto w-full max-w-[96rem] p-6 lg:p-8">
        <div className="mb-6 flex flex-col gap-2">
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Operations Dashboard</h1>
          <p className="text-sm text-zinc-500">Run outreach, review scheduled work, and monitor live processing.</p>
        </div>
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
            {/* Control Panel */}
            <div className="space-y-6">
              {!hasActiveSubscription && selectedOrganization && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200">
                  Choose an active plan before running outreach, follow-ups, scheduled sends, or inbound reply automation.
                  <Link href="/plans" className="ml-2 font-medium underline underline-offset-2">Open plans</Link>
                </div>
              )}
              {isPlatformManagementContext && selectedOrganization && (
                <div className="rounded-lg border border-sky-200 bg-sky-50 p-4 text-sm text-sky-900 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-200">
                  You are viewing {selectedOrganization.name} from the platform owner context. Tenant operations are locked here; sign in as an active tenant member to run outreach or send queued emails.
                </div>
              )}
              <div className="p-6 bg-white border border-zinc-200 rounded-lg shadow-sm dark:bg-zinc-900 dark:border-zinc-800">
                <h2 className="text-lg font-semibold mb-4 text-zinc-900 dark:text-zinc-50">Campaign Control</h2>
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-1">
                      Select Campaign
                    </label>
                    <select 
                      value={selectedCampaign}
                      onChange={(e) => setSelectedCampaign(e.target.value)}
                      className="w-full px-3 py-2 bg-zinc-50 border border-zinc-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-zinc-500 dark:bg-zinc-800 dark:border-zinc-700"
                    >
                      <option value="">Random Active Campaign</option>
                      {campaigns.map(camp => (
                        <option key={camp.id} value={camp.name}>{camp.name}</option>
                      ))}
                    </select>
                    <div className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
                      {selectedCampaignDetails
                        ? selectedCampaignDetails.auto_approve_drafts
                          ? 'Outreach approval: auto-send enabled. Campaign outreach drafts skip human review.'
                          : 'Outreach approval: review required. Campaign outreach drafts wait in Draft Approvals.'
                        : 'Approval follows the selected random campaign setting.'}
                      {selectedCampaignDetails && (
                        <span className="block">
                          {selectedCampaignDetails.auto_approve_monitor_replies
                            ? 'Monitored replies: auto-send enabled for webhook replies.'
                            : 'Monitored replies: review required for webhook replies.'}
                        </span>
                      )}
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-1">
                      Display Timezone
                    </label>
                    <select
                      value={organizationTimezone}
                      onChange={(e) => void saveOrganizationTimezone(e.target.value)}
                      className="w-full px-3 py-2 bg-zinc-50 border border-zinc-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-zinc-500 dark:bg-zinc-800 dark:border-zinc-700"
                    >
                      {TIME_ZONE_OPTIONS.map(zone => (
                        <option key={zone} value={zone}>{zone}</option>
                      ))}
                    </select>
                    <div className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
                      {selectedOrganization
                        ? `${selectedOrganization.name} times display in ${organizationTimezone}.`
                        : `Times display in ${organizationTimezone}.`}
                      {!canEditOrganizationTimezone && selectedOrganization && (
                        <span className="block">Only organization admins can save this setting.</span>
                      )}
                    </div>
                  </div>
                  <button
                    onClick={startOutreach}
                    disabled={isStreaming || !canRunOutreach}
                    className="w-full py-2 bg-zinc-900 text-white rounded-lg font-medium hover:bg-zinc-800 disabled:opacity-50 disabled:cursor-not-allowed dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200 transition-colors"
                  >
                    {isStreaming ? 'AI Agent Working...' : 'Run Outreach'}
                  </button>
                  <button
                    onClick={() => void openFollowupQueue()}
                    disabled={isStreaming || !canRunOutreach}
                    className="w-full py-2 border border-zinc-300 rounded-lg font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                  >
                    View Upcoming Follow-ups
                  </button>
                  <button
                    onClick={() => void openScheduledQueue()}
                    disabled={isStreaming || !canRunOutreach}
                    className="w-full py-2 border border-zinc-300 rounded-lg font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                  >
                    View Scheduled Sends
                  </button>
                </div>
              </div>

              <div className="p-6 bg-white border border-zinc-200 rounded-lg shadow-sm dark:bg-zinc-900 dark:border-zinc-800">
                <h3 className="text-sm font-semibold mb-2 text-zinc-500 uppercase tracking-wider">Stats</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">{analytics?.totals.active_campaigns ?? campaigns.length}</p>
                    <p className="text-xs text-zinc-500">Active Campaigns</p>
                  </div>
                  <Link href="/drafts" className="block rounded-md hover:bg-zinc-50 dark:hover:bg-zinc-800 p-1 -m-1">
                    <p className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">{analytics?.totals.pending_drafts ?? pendingDraftCount}</p>
                    <p className="text-xs text-zinc-500">Pending Drafts</p>
                  </Link>
                  <div>
                    <p className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">{analytics?.totals.scheduled_emails ?? 0}</p>
                    <p className="text-xs text-zinc-500">Scheduled Emails</p>
                  </div>
                  <div>
                    <p className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">{analytics?.totals.inbound_replies ?? 0}</p>
                    <p className="text-xs text-zinc-500">Inbound Replies</p>
                  </div>
                  <div>
                    <p className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">{analytics ? `${Math.round(analytics.rates.reply_rate * 100)}%` : '0%'}</p>
                    <p className="text-xs text-zinc-500">Reply Rate</p>
                  </div>
                  <div>
                    <p className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">{analytics?.totals.meetings_booked ?? 0}</p>
                    <p className="text-xs text-zinc-500">Meetings</p>
                  </div>
                </div>
              </div>
            </div>

            {/* Logs/Terminal */}
            <div className="flex min-w-0 flex-col gap-4">
              {/* Tab Navigation */}
              <div className="flex border-b border-zinc-200 dark:border-zinc-800">
                <button
                  className={`px-4 py-2 text-sm font-medium ${activeTab === 'outreach' ? 'border-b-2 border-zinc-900 text-zinc-900 dark:border-zinc-100 dark:text-zinc-100' : 'text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200'}`}
                  onClick={() => setActiveTab('outreach')}
                >
                  Outreach Orchestrator
                </button>
                <button
                  className={`px-4 py-2 text-sm font-medium ${activeTab === 'monitor' ? 'border-b-2 border-zinc-900 text-zinc-900 dark:border-zinc-100 dark:text-zinc-100' : 'text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200'}`}
                  onClick={() => setActiveTab('monitor')}
                >
                  Email Monitor
                  {isMonitoring && <span className="ml-2 inline-block w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>}
                </button>
              </div>

              <div className="flex-1 min-h-[500px] flex flex-col bg-zinc-900 rounded-xl border border-zinc-800 overflow-hidden shadow-xl">
                <div className="flex items-center gap-2 px-4 py-2 border-b border-zinc-800 bg-zinc-900/50">
                  <div className="w-3 h-3 rounded-full bg-red-500/20 border border-red-500/50"></div>
                  <div className="w-3 h-3 rounded-full bg-yellow-500/20 border border-yellow-500/50"></div>
                  <div className="w-3 h-3 rounded-full bg-green-500/20 border border-green-500/50"></div>
                  <span className="ml-2 text-xs font-mono text-zinc-500">
                    {activeTab === 'outreach' ? 'orchestrator-logs' : 'monitor-logs'}
                  </span>
                </div>
                <div className="flex-1 p-4 font-mono text-sm overflow-y-auto space-y-2">
                  {activeTab === 'outreach' ? (
                    <>
                      {outreachLogs.length === 0 && !isStreaming && (
                        <p className="text-zinc-600 italic">Ready to execute outreach campaign...</p>
                      )}
                      {outreachLogs.map((log, i: number) => (
                        <div key={i} className={`flex gap-3 ${
                          log.status === 'error' ? 'text-red-400' : 
                          log.status === 'success' ? 'text-emerald-400' : 
                          log.status === 'warning' ? 'text-yellow-400' :
                          'text-zinc-300'
                        }`}>
                          <span className="text-zinc-600">[{formatTime(log.timestamp, organizationTimezone)}]</span>
                          <span>{log.message}</span>
                        </div>
                      ))}
                      {isStreaming && (
                        <div className="flex gap-3 text-zinc-400 animate-pulse">
                          <span className="text-zinc-600">[{formatTime(new Date(), organizationTimezone)}]</span>
                          <span>AI Agent is thinking...</span>
                        </div>
                      )}
                    </>
                  ) : (
                    <>
                      {visibleMonitorLogs.length === 0 && !isMonitoring && (
                        <p className="text-zinc-600 italic">Connecting to Email Monitor...</p>
                      )}
                      {visibleMonitorLogs.length === 0 && isMonitoring && (
                        <p className="text-zinc-600 italic">Listening for incoming webhooks...</p>
                      )}
                      {visibleMonitorLogs.map((log, i: number) => (
                        <div key={i} className={`flex gap-3 ${
                          log.status === 'error' ? 'text-red-400' : 
                          log.status === 'success' ? 'text-emerald-400' : 
                          log.status === 'warning' ? 'text-yellow-400' :
                          'text-zinc-300'
                        }`}>
                          <span className="text-zinc-600 shrink-0">[{formatTime(log.timestamp, organizationTimezone)}]</span>
                          {log.event_id && (
                            <span className="text-violet-400 font-mono text-xs shrink-0">[{log.event_id}]</span>
                          )}
                          <span>{log.message}</span>
                        </div>
                      ))}
                    </>
                  )}
                </div>
              </div>
            </div>
          </div>
      </main>

      {scheduledOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-5xl max-h-[90vh] overflow-hidden rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 shadow-2xl">
            <div className="flex items-start justify-between gap-4 p-5 border-b border-zinc-200 dark:border-zinc-800">
              <div>
                <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Scheduled Sends</h3>
                <p className="text-sm text-zinc-600 dark:text-zinc-400">
                  Approved emails waiting for their send time. The scheduler should send due rows automatically.
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => void runScheduledSends()}
                  disabled={!canRunOutreach}
                  className="px-3 py-2 bg-zinc-900 text-white rounded-md text-sm font-medium disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
                >
                  Run Due Now
                </button>
                <button
                  onClick={() => setScheduledOpen(false)}
                  className="px-3 py-2 border border-zinc-300 rounded-md text-sm dark:border-zinc-700"
                >
                  Close
                </button>
              </div>
            </div>

            <div className="p-5 overflow-y-auto max-h-[70vh]">
              {scheduledLoading ? (
                <p className="text-sm text-zinc-500">Loading scheduled sends...</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm min-w-[920px]">
                    <thead className="bg-zinc-50 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400">
                      <tr>
                        <th className="px-3 py-2 font-medium">Email</th>
                        <th className="px-3 py-2 font-medium">Lead</th>
                        <th className="px-3 py-2 font-medium">Campaign</th>
                        <th className="px-3 py-2 font-medium">Scheduled Time</th>
                        <th className="px-3 py-2 font-medium">Attempts</th>
                        <th className="px-3 py-2 font-medium text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                      {scheduledEmails.map(email => (
                        <tr key={email.id} className="align-top">
                          <td className="px-3 py-3">
                            <div className="font-medium text-zinc-900 dark:text-zinc-100">#{email.id} {email.subject}</div>
                            <div className="text-xs text-zinc-500 line-clamp-2 max-w-md">{email.body}</div>
                            {email.last_error && <div className="text-xs text-rose-500 mt-1">{email.last_error}</div>}
                          </td>
                          <td className="px-3 py-3">
                            <div>{email.lead_name || 'Unknown'}</div>
                            <div className="text-xs text-zinc-500">{email.lead_email}</div>
                          </td>
                          <td className="px-3 py-3">{email.campaign_name}</td>
                          <td className="px-3 py-3">{formatTimestamp(email.scheduled_send_at, organizationTimezone)}</td>
                          <td className="px-3 py-3">{email.send_attempts || 0}</td>
                          <td className="px-3 py-3 text-right space-x-2">
                            <button
                              onClick={() => startEditScheduled(email)}
                              disabled={!canRunOutreach}
                              className="px-3 py-1 border border-zinc-300 rounded-md text-xs font-medium disabled:opacity-50 dark:border-zinc-700"
                            >
                              Edit
                            </button>
                            <button
                              onClick={() => void returnScheduledToReview(email)}
                              disabled={!canRunOutreach}
                              className="px-3 py-1 border border-amber-300 text-amber-700 rounded-md text-xs font-medium disabled:opacity-50 dark:border-amber-800 dark:text-amber-300"
                            >
                              Back to Review
                            </button>
                          </td>
                        </tr>
                      ))}
                      {scheduledEmails.length === 0 && (
                        <tr>
                          <td colSpan={6} className="px-6 py-8 text-center text-zinc-500">
                            No approved emails are scheduled.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}

              {editingScheduled && (
                <div className="mt-5 border border-zinc-200 dark:border-zinc-700 rounded-lg p-4 space-y-3">
                  <div className="flex items-center justify-between gap-3">
                    <h4 className="font-semibold text-zinc-900 dark:text-zinc-100">Edit scheduled email #{editingScheduled.id}</h4>
                    <button onClick={() => setEditingScheduled(null)} className="text-sm text-zinc-500">Cancel</button>
                  </div>
                  <input
                    value={scheduledSubject}
                    onChange={(e) => setScheduledSubject(e.target.value)}
                    className="w-full px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700"
                  />
                  <textarea
                    value={scheduledBody}
                    onChange={(e) => setScheduledBody(e.target.value)}
                    rows={8}
                    className="w-full px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700"
                  />
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      type="datetime-local"
                      value={scheduledTime}
                      onChange={(e) => setScheduledTime(e.target.value)}
                      className="px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700"
                    />
                    <button
                      onClick={() => void saveScheduledEdit()}
                      disabled={!canRunOutreach}
                      className="px-4 py-2 bg-zinc-900 text-white rounded-md text-sm font-medium disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
                    >
                      Save Scheduled Email
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {followupsOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-5xl max-h-[90vh] overflow-hidden rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 shadow-2xl">
            <div className="flex items-start justify-between gap-4 p-5 border-b border-zinc-200 dark:border-zinc-800">
              <div>
                <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Upcoming Follow-ups</h3>
                <p className="text-sm text-zinc-600 dark:text-zinc-400">
                  Time-based follow-ups for leads that have not replied. Webhooks do not trigger these because no inbound email occurs.
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => void generateFollowups()}
                  disabled={!canRunOutreach}
                  className="px-3 py-2 bg-zinc-900 text-white rounded-md text-sm font-medium disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
                >
                  Generate Due Drafts
                </button>
                <button
                  onClick={() => setFollowupsOpen(false)}
                  className="px-3 py-2 border border-zinc-300 rounded-md text-sm dark:border-zinc-700"
                >
                  Close
                </button>
              </div>
            </div>

            <div className="p-5 overflow-y-auto max-h-[70vh]">
              {followupsLoading ? (
                <p className="text-sm text-zinc-500">Loading follow-ups...</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm min-w-[920px]">
                    <thead className="bg-zinc-50 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400">
                      <tr>
                        <th className="px-3 py-2 font-medium">Lead</th>
                        <th className="px-3 py-2 font-medium">Campaign</th>
                        <th className="px-3 py-2 font-medium">Step</th>
                        <th className="px-3 py-2 font-medium">Last Contacted</th>
                        <th className="px-3 py-2 font-medium">Due Time</th>
                        <th className="px-3 py-2 font-medium">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                      {upcomingFollowups.map(item => (
                        <tr key={`${item.campaign_id}-${item.lead_id}-${item.step_number}`}>
                          <td className="px-3 py-3">
                            <div className="font-medium text-zinc-900 dark:text-zinc-100">{item.name || 'Unknown'}</div>
                            <div className="text-xs text-zinc-500">{item.email}</div>
                            <div className="text-xs text-zinc-500">{item.company || 'No company'}</div>
                          </td>
                          <td className="px-3 py-3">{item.campaign_name}</td>
                          <td className="px-3 py-3">Step {item.step_number} after {item.delay_days} day(s)</td>
                          <td className="px-3 py-3">{formatTimestamp(item.last_contacted_at, organizationTimezone)}</td>
                          <td className="px-3 py-3">{formatTimestamp(item.due_at, organizationTimezone)}</td>
                          <td className="px-3 py-3">
                            {item.is_due ? (
                              <span className="px-2 py-1 rounded-full text-xs font-medium bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">Due now</span>
                            ) : item.existing_message_id ? (
                              <span className="px-2 py-1 rounded-full text-xs font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
                                {item.existing_message_status} #{item.existing_message_id}
                              </span>
                            ) : (
                              <span className="px-2 py-1 rounded-full text-xs font-medium bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">Upcoming</span>
                            )}
                          </td>
                        </tr>
                      ))}
                      {upcomingFollowups.length === 0 && (
                        <tr>
                          <td colSpan={6} className="px-6 py-8 text-center text-zinc-500">
                            No upcoming follow-ups for the selected scope.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

    </AppShell>
  )
}
