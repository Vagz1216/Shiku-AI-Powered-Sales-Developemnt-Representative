'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAuth } from "@clerk/clerk-react";
import { ActionFeedback, type ActionFeedbackState } from '@/components/action-feedback'
import { AppShell } from '@/components/app-shell'
import { useTenantScope } from '@/components/tenant-scope'
import { fetchWithAuthRetry } from '@/lib/auth-fetch'
import { formatTimestamp, zonedLocalToIso } from '@/lib/time'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Draft {
  id: number
  subject: string
  body: string
  created_at: string
  draft_source: 'inbound_response' | 'outreach'
  channel: 'email' | 'whatsapp' | 'linkedin'
  deep_link_url?: string | null
  review_context?: DraftReviewContext
  lead_name: string
  lead_email: string
  campaign_name: string
  attachments: DraftAttachment[]
}

interface DraftReviewContext {
  source: 'inbound_response' | 'outreach'
  source_label: string
  generation_summary?: string | null
  review_rationale?: string | null
  selected_draft_type?: string | null
  inbound_subject?: string | null
  inbound_summary?: string | null
  inbound_received_at?: string | null
  intent?: string | null
  last_outbound_subject?: string | null
  last_outbound_summary?: string | null
  last_inbound_subject?: string | null
  last_inbound_summary?: string | null
  context_updated_at?: string | null
}

interface DraftAttachment {
  id: number
  filename: string
  content_type: string | null
  size_bytes: number
  source: string
  created_at: string | null
  has_content: boolean
}

interface AttachmentUpload {
  filename: string
  content_type: string | null
  content_base64: string
}

interface BatchApprovalSummary {
  requested?: number
  approved_sent?: number
  approved_scheduled?: number
  rejected?: number
  not_found?: number
  send_failed?: number
}

interface BatchDeleteSummary {
  requested?: number
  deleted?: number
  not_found?: number
}

function getErrorMessage(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback
}

function sourceLabel(draft: Draft) {
  if (draft.channel === 'whatsapp') return 'WhatsApp'
  if (draft.channel === 'linkedin') return 'LinkedIn'
  return draft.draft_source === 'inbound_response' ? 'Reply draft' : 'Cold outreach'
}

function sourceBadgeClass(draft: Draft) {
  if (draft.channel === 'whatsapp') return 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200'
  if (draft.channel === 'linkedin') return 'border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-800 dark:bg-blue-950/40 dark:text-blue-200'
  return draft.draft_source === 'inbound_response'
    ? 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200'
    : 'border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-200'
}

function channelLabel(channel: Draft['channel']) {
  if (channel === 'whatsapp') return '💬 WhatsApp'
  if (channel === 'linkedin') return '🔗 LinkedIn'
  return null
}

function channelBadgeClass(channel: Draft['channel']) {
  if (channel === 'whatsapp') return 'border-green-300 bg-green-50 text-green-800 dark:border-green-700 dark:bg-green-950/40 dark:text-green-300'
  if (channel === 'linkedin') return 'border-blue-300 bg-blue-50 text-blue-800 dark:border-blue-700 dark:bg-blue-950/40 dark:text-blue-300'
  return ''
}

function intentLabel(intent?: string | null) {
  if (!intent) return null
  return intent.replace(/_/g, ' ')
}

async function responseMessage(res: Response, fallback: string) {
  try {
    const data = await res.json()
    return data.detail || data.error || data.message || fallback
  } catch {
    return fallback
  }
}

async function responseJson<T>(res: Response): Promise<T> {
  try {
    return await res.json() as T
  } catch {
    return {} as T
  }
}

function batchApprovalFeedback(
  summary: BatchApprovalSummary | undefined,
  approved: boolean,
  scheduled: boolean,
): NonNullable<ActionFeedbackState> {
  const requested = summary?.requested || 0
  const sent = summary?.approved_sent || 0
  const scheduledCount = summary?.approved_scheduled || 0
  const rejected = summary?.rejected || 0
  const notFound = summary?.not_found || 0
  const failed = summary?.send_failed || 0
  const issues = notFound + failed
  const issueMessage = issues > 0
    ? ` ${failed} failed, ${notFound} were already processed or missing.`
    : ''

  if (approved && scheduled) {
    return {
      type: issues > 0 ? 'warning' : 'success',
      message: `Scheduled ${scheduledCount} of ${requested} selected draft(s).${issueMessage}`,
    }
  }

  if (approved) {
    return {
      type: issues > 0 ? 'warning' : 'success',
      message: `Approved and sent ${sent} of ${requested} selected draft(s).${issueMessage}`,
    }
  }

  return {
    type: issues > 0 ? 'warning' : 'success',
    message: `Rejected ${rejected} of ${requested} selected draft(s).${issueMessage}`,
  }
}

function batchDeleteFeedback(summary: BatchDeleteSummary | undefined): NonNullable<ActionFeedbackState> {
  const requested = summary?.requested || 0
  const deleted = summary?.deleted || 0
  const notFound = summary?.not_found || 0

  return {
    type: notFound > 0 ? 'warning' : 'success',
    message: `Deleted ${deleted} of ${requested} selected draft(s).${notFound > 0 ? ` ${notFound} were already processed or missing.` : ''}`,
  }
}

export default function DraftsPage() {
  const { isLoaded, userId, getToken } = useAuth()
  const { selectedOrganizationId, selectedOrganization, orgUrl } = useTenantScope()
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [loading, setLoading] = useState(true)
  const [feedback, setFeedback] = useState<ActionFeedbackState>(null)
  const [query, setQuery] = useState('')
  const [sourceFilter, setSourceFilter] = useState<'all' | 'inbound_response' | 'outreach' | 'whatsapp' | 'linkedin'>('all')
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [busy, setBusy] = useState(false)
  const [stopFutureAttempts, setStopFutureAttempts] = useState(true)
  const [viewingDraft, setViewingDraft] = useState<Draft | null>(null)
  const [editSubject, setEditSubject] = useState('')
  const [editBody, setEditBody] = useState('')
  const [newFiles, setNewFiles] = useState<File[]>([])
  const [savingEdit, setSavingEdit] = useState(false)
  const [scheduledSendAt, setScheduledSendAt] = useState('')
  const canReviewDrafts = !!selectedOrganization?.capabilities?.can_review_drafts

  const authedFetch = useCallback((url: string, init: RequestInit = {}) => {
    return fetchWithAuthRetry(getToken, url, init)
  }, [getToken])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return drafts.filter(d => {
      if (sourceFilter === 'whatsapp' && d.channel !== 'whatsapp') return false
      if (sourceFilter === 'linkedin' && d.channel !== 'linkedin') return false
      if (sourceFilter === 'inbound_response' && d.draft_source !== 'inbound_response') return false
      if (sourceFilter === 'outreach' && d.draft_source !== 'outreach') return false
      if (!q) return true
      return (
        d.subject.toLowerCase().includes(q) ||
        d.body.toLowerCase().includes(q) ||
        d.lead_name.toLowerCase().includes(q) ||
        d.lead_email.toLowerCase().includes(q) ||
        d.campaign_name.toLowerCase().includes(q) ||
        sourceLabel(d).toLowerCase().includes(q) ||
        (d.review_context?.inbound_summary || '').toLowerCase().includes(q) ||
        (d.review_context?.last_outbound_summary || '').toLowerCase().includes(q) ||
        (d.review_context?.generation_summary || '').toLowerCase().includes(q) ||
        (d.review_context?.review_rationale || '').toLowerCase().includes(q) ||
        (d.attachments || []).some(a => a.filename.toLowerCase().includes(q)) ||
        String(d.id).includes(q)
      )
    })
  }, [drafts, query, sourceFilter])

  const visibleIds = useMemo(() => filtered.map(d => d.id), [filtered])
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every(id => selectedIds.includes(id))

  const loadDrafts = useCallback(async () => {
    try {
      setLoading(true)
      if (!selectedOrganizationId) return
      const res = await authedFetch(orgUrl(`${API_BASE}/api/drafts`))
      if (!res.ok) throw new Error('Failed to load drafts')
      const data = await res.json() as { drafts?: Draft[] }
      setDrafts(data.drafts || [])
      setSelectedIds([])
    } catch (err: unknown) {
      setFeedback({ type: 'error', message: getErrorMessage(err, 'Failed to load drafts') })
    } finally {
      setLoading(false)
    }
  }, [authedFetch, orgUrl, selectedOrganizationId])

  useEffect(() => {
    if (isLoaded && userId && selectedOrganizationId) {
      const timer = window.setTimeout(() => {
        void loadDrafts()
      }, 0)
      return () => window.clearTimeout(timer)
    }
  }, [isLoaded, userId, selectedOrganizationId, loadDrafts])

  const toggleSelected = (draftId: number) => {
    setSelectedIds(prev => prev.includes(draftId) ? prev.filter(id => id !== draftId) : [...prev, draftId])
  }

  const toggleSelectVisible = () => {
    if (allVisibleSelected) {
      setSelectedIds(prev => prev.filter(id => !visibleIds.includes(id)))
      return
    }
    setSelectedIds(prev => Array.from(new Set([...prev, ...visibleIds])))
  }

  const openDraft = (draft: Draft) => {
    setFeedback(null)
    setViewingDraft(draft)
    setEditSubject(draft.subject)
    setEditBody(draft.body)
    setNewFiles([])
  }

  const fileToAttachment = (file: File): Promise<AttachmentUpload> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => {
        const result = String(reader.result || '')
        resolve({
          filename: file.name,
          content_type: file.type || null,
          content_base64: result.includes(',') ? result.split(',', 2)[1] : result
        })
      }
      reader.onerror = () => reject(new Error(`Failed to read ${file.name}`))
      reader.readAsDataURL(file)
    })
  }

  const saveDraftEdits = async (reload = true): Promise<boolean> => {
    if (!viewingDraft) return false
    if (!editSubject.trim() || !editBody.trim()) {
      setFeedback({ type: 'error', message: 'Subject and body are required.' })
      return false
    }
    try {
      setFeedback(null)
      setSavingEdit(true)
      const updateRes = await authedFetch(orgUrl(`${API_BASE}/api/drafts/${viewingDraft.id}`), {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ subject: editSubject, body: editBody })
      })
      if (!updateRes.ok) throw new Error('Failed to save draft edits')

      let attachments = viewingDraft.attachments || []
      if (newFiles.length > 0) {
        const uploads = await Promise.all(newFiles.map(fileToAttachment))
        const attachmentRes = await authedFetch(orgUrl(`${API_BASE}/api/drafts/${viewingDraft.id}/attachments`), {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ attachments: uploads })
        })
        if (!attachmentRes.ok) throw new Error('Failed to add attachments')
        const attachmentData = await attachmentRes.json() as { result?: { attachments?: DraftAttachment[] } }
        attachments = attachmentData.result?.attachments || attachments
      }

      const updatedDraft = {
        ...viewingDraft,
        subject: editSubject,
        body: editBody,
        attachments
      }
      setViewingDraft(updatedDraft)
      setNewFiles([])
      if (reload) await loadDrafts()
      if (reload) setFeedback({ type: 'success', message: `Draft #${viewingDraft.id} saved.` })
      return true
    } catch (err: unknown) {
      setFeedback({ type: 'error', message: getErrorMessage(err, 'Failed to save draft') })
      return false
    } finally {
      setSavingEdit(false)
    }
  }

  const deleteAttachment = async (attachmentId: number) => {
    if (!viewingDraft) return
    try {
      setFeedback(null)
      setSavingEdit(true)
      const res = await authedFetch(orgUrl(`${API_BASE}/api/drafts/${viewingDraft.id}/attachments/${attachmentId}`), {
        method: 'DELETE',
      })
      if (!res.ok) throw new Error('Failed to remove attachment')
      const data = await res.json() as { result?: { attachments?: DraftAttachment[] } }
      const attachments = data.result?.attachments || []
      setViewingDraft({ ...viewingDraft, attachments })
      await loadDrafts()
      setFeedback({ type: 'success', message: 'Attachment removed from draft.' })
    } catch (err: unknown) {
      setFeedback({ type: 'error', message: getErrorMessage(err, 'Failed to remove attachment') })
    } finally {
      setSavingEdit(false)
    }
  }

  const scheduleIso = (value = scheduledSendAt) => {
    if (!value.trim()) return null
    return zonedLocalToIso(value, selectedOrganization?.timezone)
  }

  const saveThenApprove = async () => {
    if (!viewingDraft) return
    const ok = await saveDraftEdits(false)
    if (!ok) return
    const draftId = viewingDraft.id
    setViewingDraft(null)
    await singleAction(draftId, true)
  }

  const saveThenSchedule = async () => {
    if (!viewingDraft) return
    if (!scheduledSendAt.trim()) {
      setFeedback({ type: 'error', message: 'Choose a scheduled send time first.' })
      return
    }
    const ok = await saveDraftEdits(false)
    if (!ok) return
    const draftId = viewingDraft.id
    setViewingDraft(null)
    await singleAction(draftId, true, scheduledSendAt)
  }

  const singleAction = async (draftId: number, approved: boolean, scheduledAt = '') => {
    try {
      setFeedback(null)
      setBusy(true)
      const payload = {
        approved,
        scheduled_send_at: approved && scheduledAt.trim() ? scheduleIso(scheduledAt) : null,
      }
      const res = await authedFetch(orgUrl(`${API_BASE}/api/drafts/${draftId}/approve`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      })
      if (!res.ok) throw new Error(await responseMessage(res, 'Failed to process draft action'))
      const data = await responseJson<{ message?: string }>(res)
      await loadDrafts()
      setFeedback({
        type: 'success',
        message: data.message || (approved ? 'Draft approved and sent.' : 'Draft rejected.'),
      })
    } catch (err: unknown) {
      setFeedback({ type: 'error', message: getErrorMessage(err, 'Action failed') })
    } finally {
      setBusy(false)
    }
  }

  const batchAction = async (approved: boolean, scheduledAt = '') => {
    if (selectedIds.length === 0) return
    try {
      setFeedback(null)
      setBusy(true)
      const payload = {
        draft_ids: selectedIds,
        approved,
        scheduled_send_at: approved && scheduledAt.trim() ? scheduleIso(scheduledAt) : null,
      }
      const res = await authedFetch(orgUrl(`${API_BASE}/api/drafts/batch-approve`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      })
      if (!res.ok) throw new Error(await responseMessage(res, 'Batch action failed'))
      const data = await responseJson<{ summary?: BatchApprovalSummary }>(res)
      await loadDrafts()
      setFeedback(batchApprovalFeedback(data.summary, approved, !!scheduledAt.trim()))
    } catch (err: unknown) {
      setFeedback({ type: 'error', message: getErrorMessage(err, 'Batch action failed') })
    } finally {
      setBusy(false)
    }
  }

  const singleDelete = async (draftId: number) => {
    if (!confirm(`Delete draft #${draftId}?`)) return
    try {
      setFeedback(null)
      setBusy(true)
      const res = await authedFetch(
        orgUrl(`${API_BASE}/api/drafts/${draftId}?stop_future_attempts=${stopFutureAttempts}`),
        {
          method: 'DELETE',
        }
      )
      if (!res.ok) throw new Error(await responseMessage(res, 'Failed to delete draft'))
      await loadDrafts()
      setFeedback({ type: 'success', message: `Draft #${draftId} deleted.` })
    } catch (err: unknown) {
      setFeedback({ type: 'error', message: getErrorMessage(err, 'Delete failed') })
    } finally {
      setBusy(false)
    }
  }

  const batchDelete = async () => {
    if (selectedIds.length === 0) return
    if (!confirm(`Delete ${selectedIds.length} selected draft(s)?`)) return
    try {
      setFeedback(null)
      setBusy(true)
      const res = await authedFetch(orgUrl(`${API_BASE}/api/drafts/batch-delete`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          draft_ids: selectedIds,
          stop_future_attempts: stopFutureAttempts
        })
      })
      if (!res.ok) throw new Error(await responseMessage(res, 'Batch delete failed'))
      const data = await responseJson<{ summary?: BatchDeleteSummary }>(res)
      await loadDrafts()
      setFeedback(batchDeleteFeedback(data.summary))
    } catch (err: unknown) {
      setFeedback({ type: 'error', message: getErrorMessage(err, 'Batch delete failed') })
    } finally {
      setBusy(false)
    }
  }

  const markAsSent = async (draft: Draft) => {
    try {
      setFeedback(null)
      setBusy(true)
      const res = await authedFetch(orgUrl(`${API_BASE}/api/drafts/${draft.id}/mark-sent`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      })
      if (!res.ok) throw new Error(await responseMessage(res, 'Failed to mark as sent'))
      await loadDrafts()
      setFeedback({ type: 'success', message: `Draft #${draft.id} marked as sent.` })
    } catch (err: unknown) {
      setFeedback({ type: 'error', message: getErrorMessage(err, 'Mark as sent failed') })
    } finally {
      setBusy(false)
    }
  }

  const copyToClipboard = async (text: string, draftId: number) => {
    try {
      await navigator.clipboard.writeText(text)
      setFeedback({ type: 'success', message: `Draft #${draftId} text copied to clipboard.` })
    } catch {
      setFeedback({ type: 'error', message: 'Failed to copy text to clipboard.' })
    }
  }

  if (!isLoaded || !userId) {
    return <div className="flex items-center justify-center min-h-screen">Loading or unauthorized...</div>
  }

  return (
    <AppShell active="drafts">
      <main className="flex-1 max-w-7xl mx-auto w-full p-4 sm:p-6 lg:p-8">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-6">
          <h2 className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">Draft Approvals</h2>
          <div className="flex w-full flex-col gap-3 sm:flex-row md:w-auto">
            <input
              type="text"
              placeholder="Search by id, lead, campaign, subject..."
              value={query}
              onChange={e => setQuery(e.target.value)}
              className="w-full px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700 sm:w-80"
            />
            <button
              disabled={busy}
              onClick={() => loadDrafts()}
              className="px-3 py-2 border border-zinc-300 rounded-md text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              Refresh
            </button>
          </div>
        </div>

        <ActionFeedback feedback={feedback} onDismiss={() => setFeedback(null)} className="mb-4" />

        <div className="mb-4 flex flex-wrap gap-2">
          {[
            { key: 'all', label: 'All drafts' },
            { key: 'inbound_response', label: 'Reply drafts' },
            { key: 'outreach', label: 'Cold outreach' },
            { key: 'whatsapp', label: '💬 WhatsApp' },
            { key: 'linkedin', label: '🔗 LinkedIn' },
          ].map(option => (
            <button
              key={option.key}
              type="button"
              onClick={() => setSourceFilter(option.key as 'all' | 'inbound_response' | 'outreach' | 'whatsapp' | 'linkedin')}
              className={sourceFilter === option.key
                ? 'rounded-md bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white dark:bg-zinc-100 dark:text-zinc-900'
                : 'rounded-md border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 dark:border-zinc-700 dark:text-zinc-200'}
            >
              {option.label}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-3 mb-4">
          <button
            disabled={busy || selectedIds.length === 0 || !canReviewDrafts}
            onClick={() => batchAction(true)}
            className="px-4 py-2 bg-emerald-600 text-white rounded-md text-sm font-medium disabled:opacity-50"
          >
            Approve Selected ({selectedIds.length})
          </button>
          <input
            type="datetime-local"
            value={scheduledSendAt}
            onChange={(e) => setScheduledSendAt(e.target.value)}
            className="px-3 py-2 border rounded-md text-sm dark:bg-zinc-800 dark:border-zinc-700"
          />
          <button
            disabled={busy || selectedIds.length === 0 || !scheduledSendAt.trim() || !canReviewDrafts}
            onClick={() => batchAction(true, scheduledSendAt)}
            className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm font-medium disabled:opacity-50"
          >
            Schedule Selected ({selectedIds.length})
          </button>
          <button
            disabled={busy || selectedIds.length === 0 || !canReviewDrafts}
            onClick={() => batchAction(false)}
            className="px-4 py-2 bg-rose-600 text-white rounded-md text-sm font-medium disabled:opacity-50"
          >
            Reject Selected ({selectedIds.length})
          </button>
          <button
            disabled={busy || selectedIds.length === 0 || !canReviewDrafts}
            onClick={batchDelete}
            className="px-4 py-2 bg-zinc-800 text-white rounded-md text-sm font-medium disabled:opacity-50 dark:bg-zinc-200 dark:text-zinc-900"
          >
            Delete Selected ({selectedIds.length})
          </button>
          <button
            disabled={busy || visibleIds.length === 0}
            onClick={toggleSelectVisible}
            className="px-4 py-2 border border-zinc-300 rounded-md text-sm font-medium disabled:opacity-50 dark:border-zinc-700"
          >
            {allVisibleSelected ? 'Clear Visible' : 'Select Visible'}
          </button>
          <label className="flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-400">
            <input
              type="checkbox"
              checked={stopFutureAttempts}
              onChange={(e) => setStopFutureAttempts(e.target.checked)}
            />
            Stop future attempts when deleting
          </label>
          <span className="text-sm text-zinc-500">
            Showing {filtered.length} of {drafts.length} pending drafts
          </span>
        </div>

        <div className="hidden overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900 md:block">
          {loading ? (
            <p className="p-6 text-zinc-500">Loading drafts...</p>
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="bg-zinc-50 border-b border-zinc-200 dark:bg-zinc-800 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400">
                <tr>
                  <th className="px-4 py-3 font-medium w-10"></th>
                  <th className="px-4 py-3 font-medium">Draft</th>
                  <th className="px-4 py-3 font-medium">Source</th>
                  <th className="px-4 py-3 font-medium">Lead</th>
                  <th className="px-4 py-3 font-medium">Campaign</th>
                  <th className="px-4 py-3 font-medium">Created</th>
                  <th className="px-4 py-3 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                {filtered.map(draft => (
                  <tr key={draft.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/50 align-top">
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(draft.id)}
                        onChange={() => toggleSelected(draft.id)}
                      />
                    </td>
                    <td className="px-4 py-3">
                      <div className="font-medium text-zinc-900 dark:text-zinc-100">#{draft.id} — {draft.subject}</div>
                      <div className="text-xs text-zinc-500 max-w-xl line-clamp-2">{draft.body}</div>
                      {draft.draft_source === 'inbound_response' && draft.review_context?.inbound_summary && (
                        <div className="mt-2 max-w-xl text-xs text-zinc-600 dark:text-zinc-400">
                          Reply context: {draft.review_context.inbound_summary}
                        </div>
                      )}
                      {(draft.attachments || []).length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {draft.attachments.map(attachment => (
                            <span
                              key={attachment.id}
                              className="px-2 py-0.5 rounded border border-zinc-200 text-[11px] text-zinc-600 dark:border-zinc-700 dark:text-zinc-300"
                            >
                              {attachment.filename}
                            </span>
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-medium ${sourceBadgeClass(draft)}`}>
                        {sourceLabel(draft)}
                      </span>
                      {channelLabel(draft.channel) && (
                        <span className={`ml-1.5 inline-flex rounded-md border px-2 py-1 text-xs font-medium ${channelBadgeClass(draft.channel)}`}>
                          {channelLabel(draft.channel)}
                        </span>
                      )}
                      {intentLabel(draft.review_context?.intent) && (
                        <div className="mt-2 text-xs capitalize text-zinc-500">{intentLabel(draft.review_context?.intent)}</div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300">
                      <div>{draft.lead_name}</div>
                      <div className="text-xs text-zinc-500">{draft.lead_email}</div>
                    </td>
                    <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300">{draft.campaign_name}</td>
                    <td className="px-4 py-3 text-zinc-500">{formatTimestamp(draft.created_at, selectedOrganization?.timezone)}</td>
                    <td className="px-4 py-3 text-right space-x-1.5 space-y-1">
                      <button
                        disabled={busy || !canReviewDrafts}
                        onClick={() => openDraft(draft)}
                        className="px-3 py-1 bg-zinc-600 text-white rounded-md text-xs font-medium disabled:opacity-50"
                      >
                        Review
                      </button>
                      {draft.channel === 'email' && (
                        <>
                          <button
                            disabled={busy || !canReviewDrafts}
                            onClick={() => singleAction(draft.id, true)}
                            className="px-3 py-1 bg-emerald-600 text-white rounded-md text-xs font-medium disabled:opacity-50"
                          >
                            Approve
                          </button>
                          <button
                            disabled={busy || !scheduledSendAt.trim() || !canReviewDrafts}
                            onClick={() => singleAction(draft.id, true, scheduledSendAt)}
                            className="px-3 py-1 bg-blue-600 text-white rounded-md text-xs font-medium disabled:opacity-50"
                          >
                            Schedule
                          </button>
                        </>
                      )}
                      {draft.channel === 'whatsapp' && (
                        draft.deep_link_url ? (
                          <a
                            href={draft.deep_link_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-block px-3 py-1 bg-green-600 text-white rounded-md text-xs font-medium"
                          >
                            Open in WhatsApp
                          </a>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-3 py-1 bg-amber-100 text-amber-800 border border-amber-300 rounded-md text-xs font-medium dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-700" title="Add a phone number to this lead to enable the WhatsApp link">
                            ⚠ No phone number
                          </span>
                        )
                      )}
                      {draft.channel === 'linkedin' && (
                        <>
                          <button
                            disabled={busy}
                            onClick={() => void copyToClipboard(draft.body, draft.id)}
                            className="px-3 py-1 bg-blue-700 text-white rounded-md text-xs font-medium disabled:opacity-50"
                          >
                            Copy Text
                          </button>
                          {draft.deep_link_url && (
                            <a
                              href={draft.deep_link_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-block px-3 py-1 bg-blue-500 text-white rounded-md text-xs font-medium"
                            >
                              Open LinkedIn
                            </a>
                          )}
                        </>
                      )}
                      {(draft.channel === 'whatsapp' || draft.channel === 'linkedin') && (
                        <button
                          disabled={busy || !canReviewDrafts}
                          onClick={() => void markAsSent(draft)}
                          className="px-3 py-1 bg-emerald-600 text-white rounded-md text-xs font-medium disabled:opacity-50"
                        >
                          Mark as Sent
                        </button>
                      )}
                      <button
                        disabled={busy || !canReviewDrafts}
                        onClick={() => singleAction(draft.id, false)}
                        className="px-3 py-1 bg-rose-600 text-white rounded-md text-xs font-medium disabled:opacity-50"
                      >
                        Reject
                      </button>
                      <button
                        disabled={busy || !canReviewDrafts}
                        onClick={() => singleDelete(draft.id)}
                        className="px-3 py-1 bg-zinc-800 text-white rounded-md text-xs font-medium disabled:opacity-50 dark:bg-zinc-200 dark:text-zinc-900"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-6 py-8 text-center text-zinc-500">
                      No pending drafts found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>

        <div className="space-y-3 md:hidden">
          {loading ? (
            <p className="rounded-xl border border-zinc-200 bg-white p-5 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">Loading drafts...</p>
          ) : filtered.length === 0 ? (
            <p className="rounded-xl border border-zinc-200 bg-white p-5 text-center text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">No pending drafts found.</p>
          ) : filtered.map(draft => (
            <article key={draft.id} className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
              <div className="flex items-start gap-3">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={selectedIds.includes(draft.id)}
                  onChange={() => toggleSelected(draft.id)}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-medium ${sourceBadgeClass(draft)}`}>
                      {sourceLabel(draft)}
                    </span>
                    {intentLabel(draft.review_context?.intent) && (
                      <span className="text-xs capitalize text-zinc-500">{intentLabel(draft.review_context?.intent)}</span>
                    )}
                  </div>
                  <h3 className="mt-2 text-sm font-semibold text-zinc-900 dark:text-zinc-100">#{draft.id} — {draft.subject}</h3>
                  <p className="mt-1 line-clamp-3 text-xs text-zinc-500">{draft.body}</p>
                  {draft.draft_source === 'inbound_response' && draft.review_context?.inbound_summary && (
                    <p className="mt-2 text-xs text-zinc-600 dark:text-zinc-400">
                      Reply context: {draft.review_context.inbound_summary}
                    </p>
                  )}
                  <div className="mt-3 space-y-1 text-xs text-zinc-500">
                    <div>{draft.lead_name} · {draft.lead_email}</div>
                    <div>{draft.campaign_name}</div>
                    <div>{formatTimestamp(draft.created_at, selectedOrganization?.timezone)}</div>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <button disabled={busy || !canReviewDrafts} onClick={() => openDraft(draft)} className="rounded-md bg-zinc-600 px-3 py-2 text-xs font-medium text-white disabled:opacity-50">Review</button>
                    <button disabled={busy || !canReviewDrafts} onClick={() => singleAction(draft.id, true)} className="rounded-md bg-emerald-600 px-3 py-2 text-xs font-medium text-white disabled:opacity-50">Approve</button>
                    <button disabled={busy || !scheduledSendAt.trim() || !canReviewDrafts} onClick={() => singleAction(draft.id, true, scheduledSendAt)} className="rounded-md bg-blue-600 px-3 py-2 text-xs font-medium text-white disabled:opacity-50">Schedule</button>
                    <button disabled={busy || !canReviewDrafts} onClick={() => singleAction(draft.id, false)} className="rounded-md bg-rose-600 px-3 py-2 text-xs font-medium text-white disabled:opacity-50">Reject</button>
                    <button disabled={busy || !canReviewDrafts} onClick={() => singleDelete(draft.id)} className="col-span-2 rounded-md bg-zinc-800 px-3 py-2 text-xs font-medium text-white disabled:opacity-50 dark:bg-zinc-200 dark:text-zinc-900">Delete</button>
                  </div>
                </div>
              </div>
            </article>
          ))}
        </div>

        {viewingDraft && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
            <div className="w-full max-w-4xl max-h-[90vh] overflow-hidden rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 shadow-2xl">
              <div className="flex items-start justify-between gap-4 p-5 border-b border-zinc-200 dark:border-zinc-800">
                <div>
                  <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
                    Draft #{viewingDraft.id}
                  </h3>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-medium ${sourceBadgeClass(viewingDraft)}`}>
                      {sourceLabel(viewingDraft)}
                    </span>
                    {intentLabel(viewingDraft.review_context?.intent) && (
                      <span className="text-xs capitalize text-zinc-500">{intentLabel(viewingDraft.review_context?.intent)}</span>
                    )}
                  </div>
                  <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">Review and edit before approval</p>
                  <p className="text-xs text-zinc-500 mt-1">
                    {viewingDraft.lead_name} ({viewingDraft.lead_email}) • {viewingDraft.campaign_name}
                  </p>
                </div>
                <button
                  onClick={() => setViewingDraft(null)}
                  className="px-3 py-1 text-sm border border-zinc-300 rounded-md dark:border-zinc-700"
                >
                  Close
                </button>
              </div>
              <ActionFeedback feedback={feedback} onDismiss={() => setFeedback(null)} className="mx-5 mt-4" />

              <div className="p-5 overflow-y-auto max-h-[62vh] space-y-5">
                <div className="text-xs text-zinc-500">Created: {formatTimestamp(viewingDraft.created_at, selectedOrganization?.timezone)}</div>

                <section className="space-y-3 border-y border-zinc-200 py-4 dark:border-zinc-800">
                  <div>
                    <div className="text-xs font-medium uppercase text-zinc-500">Review context</div>
                    <p className="mt-1 text-sm text-zinc-700 dark:text-zinc-300">
                      {viewingDraft.draft_source === 'inbound_response'
                        ? 'This outbound draft was generated because the lead replied.'
                        : 'This outbound draft was generated as cold outreach.'}
                    </p>
                  </div>

                  {viewingDraft.review_context?.inbound_summary && (
                    <div>
                      <div className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Latest inbound message</div>
                      <p className="mt-1 text-sm text-zinc-800 dark:text-zinc-200">
                        {viewingDraft.review_context.inbound_summary}
                      </p>
                      <div className="mt-1 text-xs text-zinc-500">
                        {viewingDraft.review_context.inbound_subject && `Subject: ${viewingDraft.review_context.inbound_subject}`}
                        {viewingDraft.review_context.inbound_received_at && (
                          <span>
                            {viewingDraft.review_context.inbound_subject ? ' · ' : ''}
                            Received: {formatTimestamp(viewingDraft.review_context.inbound_received_at, selectedOrganization?.timezone)}
                          </span>
                        )}
                      </div>
                    </div>
                  )}

                  {viewingDraft.review_context?.generation_summary && (
                    <div>
                      <div className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Why this draft was generated</div>
                      <p className="mt-1 text-sm text-zinc-800 dark:text-zinc-200">
                        {viewingDraft.review_context.generation_summary}
                      </p>
                    </div>
                  )}

                  {viewingDraft.review_context?.review_rationale && (
                    <div>
                      <div className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Agent selection rationale</div>
                      <p className="mt-1 text-sm text-zinc-800 dark:text-zinc-200">
                        {viewingDraft.review_context.review_rationale}
                      </p>
                      {viewingDraft.review_context.selected_draft_type && (
                        <div className="mt-1 text-xs capitalize text-zinc-500">
                          Selected draft: {viewingDraft.review_context.selected_draft_type}
                        </div>
                      )}
                    </div>
                  )}

                  {viewingDraft.review_context?.last_outbound_summary && (
                    <div>
                      <div className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Previous outbound context</div>
                      <p className="mt-1 text-sm text-zinc-800 dark:text-zinc-200">
                        {viewingDraft.review_context.last_outbound_summary}
                      </p>
                      {viewingDraft.review_context.last_outbound_subject && (
                        <div className="mt-1 text-xs text-zinc-500">Subject: {viewingDraft.review_context.last_outbound_subject}</div>
                      )}
                    </div>
                  )}

                  {viewingDraft.review_context?.last_inbound_summary && (
                    <div>
                      <div className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Conversation memory</div>
                      <p className="mt-1 text-sm text-zinc-800 dark:text-zinc-200">
                        {viewingDraft.review_context.last_inbound_summary}
                      </p>
                    </div>
                  )}

                  {!viewingDraft.review_context?.inbound_summary &&
                    !viewingDraft.review_context?.generation_summary &&
                    !viewingDraft.review_context?.review_rationale &&
                    !viewingDraft.review_context?.last_outbound_summary &&
                    !viewingDraft.review_context?.last_inbound_summary && (
                      <p className="text-sm text-zinc-500">
                        No conversation context has been recorded for this draft yet.
                      </p>
                    )}
                </section>

                {viewingDraft.channel === 'email' && (
                  <label className="block">
                    <span className="block text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-1">Subject</span>
                    <input
                      type="text"
                      value={editSubject}
                      onChange={e => setEditSubject(e.target.value)}
                      className="w-full px-3 py-2 border rounded-md text-sm dark:bg-zinc-800 dark:border-zinc-700"
                    />
                  </label>
                )}

                <label className="block">
                  <span className="block text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-1">Body</span>
                  <textarea
                    value={editBody}
                    onChange={e => setEditBody(e.target.value)}
                    rows={14}
                    className="w-full px-3 py-2 border rounded-md text-sm leading-relaxed resize-y dark:bg-zinc-800 dark:border-zinc-700"
                  />
                </label>

                <div>
                  <div className="text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-2">Attachments</div>
                  <div className="space-y-2">
                    {(viewingDraft.attachments || []).map(attachment => (
                      <div
                        key={attachment.id}
                        className="flex items-center justify-between gap-3 rounded-md border border-zinc-200 px-3 py-2 dark:border-zinc-700"
                      >
                        <div className="min-w-0">
                          <div className="truncate text-sm text-zinc-800 dark:text-zinc-200">{attachment.filename}</div>
                          <div className="text-xs text-zinc-500">
                            {attachment.content_type || 'file'} • {Math.ceil((attachment.size_bytes || 0) / 1024)} KB
                          </div>
                        </div>
                        <button
                          disabled={savingEdit || busy}
                          onClick={() => void deleteAttachment(attachment.id)}
                          className="px-3 py-1 border border-zinc-300 rounded-md text-xs font-medium disabled:opacity-50 dark:border-zinc-700"
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                    {(viewingDraft.attachments || []).length === 0 && (
                      <div className="text-sm text-zinc-500">No attachments added.</div>
                    )}
                  </div>

                  {newFiles.length > 0 && (
                    <div className="mt-3 space-y-1">
                      {newFiles.map(file => (
                        <div key={`${file.name}-${file.size}`} className="text-xs text-zinc-600 dark:text-zinc-400">
                          Pending: {file.name} • {Math.ceil(file.size / 1024)} KB
                        </div>
                      ))}
                    </div>
                  )}

                  <input
                    type="file"
                    multiple
                    onChange={e => setNewFiles(Array.from(e.target.files || []))}
                    className="mt-3 block w-full text-sm text-zinc-700 file:mr-4 file:rounded-md file:border-0 file:bg-zinc-900 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white dark:text-zinc-300 dark:file:bg-zinc-100 dark:file:text-zinc-900"
                  />
                </div>
              </div>

              <div className="p-5 border-t border-zinc-200 dark:border-zinc-800 flex flex-wrap gap-2 justify-end">
                {viewingDraft.channel === 'email' && (
                  <input
                    type="datetime-local"
                    value={scheduledSendAt}
                    onChange={(e) => setScheduledSendAt(e.target.value)}
                    className="px-3 py-2 border rounded-md text-sm dark:bg-zinc-800 dark:border-zinc-700"
                  />
                )}
                <button
                  disabled={busy || savingEdit}
                  onClick={() => void saveDraftEdits()}
                  className="px-3 py-2 border border-zinc-300 rounded-md text-sm font-medium disabled:opacity-50 dark:border-zinc-700"
                >
                  {savingEdit ? 'Saving...' : 'Save Changes'}
                </button>
                {viewingDraft.channel === 'email' && (
                  <>
                    <button
                      disabled={busy || savingEdit}
                      onClick={() => void saveThenApprove()}
                      className="px-3 py-2 bg-emerald-600 text-white rounded-md text-sm font-medium disabled:opacity-50"
                    >
                      Save and Approve
                    </button>
                    <button
                      disabled={busy || savingEdit || !scheduledSendAt.trim()}
                      onClick={() => void saveThenSchedule()}
                      className="px-3 py-2 bg-blue-600 text-white rounded-md text-sm font-medium disabled:opacity-50"
                    >
                      Save and Schedule
                    </button>
                  </>
                )}
                {viewingDraft.channel === 'whatsapp' && (
                  viewingDraft.deep_link_url ? (
                    <a
                      href={viewingDraft.deep_link_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center px-3 py-2 bg-green-600 text-white rounded-md text-sm font-medium"
                    >
                      Open in WhatsApp
                    </a>
                  ) : (
                    <div className="flex flex-col gap-1">
                      <span className="inline-flex items-center gap-1.5 px-3 py-2 bg-amber-100 text-amber-800 border border-amber-300 rounded-md text-sm font-medium dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-700">
                        ⚠ No phone number on file
                      </span>
                      <p className="text-xs text-zinc-500 dark:text-zinc-400">Edit the lead to add a phone number, then re-run the campaign to generate a valid wa.me link.</p>
                    </div>
                  )
                )}
                {viewingDraft.channel === 'linkedin' && (
                  <>
                    <button
                      onClick={() => void copyToClipboard(editBody, viewingDraft.id)}
                      className="px-3 py-2 bg-blue-700 text-white rounded-md text-sm font-medium"
                    >
                      Copy Text
                    </button>
                    {viewingDraft.deep_link_url && (
                      <a
                        href={viewingDraft.deep_link_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center px-3 py-2 bg-blue-500 text-white rounded-md text-sm font-medium"
                      >
                        Open LinkedIn
                      </a>
                    )}
                  </>
                )}
                {(viewingDraft.channel === 'whatsapp' || viewingDraft.channel === 'linkedin') && (
                  <button
                    disabled={busy || savingEdit}
                    onClick={() => {
                      void markAsSent(viewingDraft)
                      setViewingDraft(null)
                    }}
                    className="px-3 py-2 bg-emerald-600 text-white rounded-md text-sm font-medium disabled:opacity-50"
                  >
                    Mark as Sent
                  </button>
                )}
                <button
                  disabled={busy || savingEdit}
                  onClick={() => {
                    void singleAction(viewingDraft.id, false)
                    setViewingDraft(null)
                  }}
                  className="px-3 py-2 bg-rose-600 text-white rounded-md text-sm font-medium disabled:opacity-50"
                >
                  Reject
                </button>
                <button
                  disabled={busy || savingEdit}
                  onClick={() => {
                    void singleDelete(viewingDraft.id)
                    setViewingDraft(null)
                  }}
                  className="px-3 py-2 bg-zinc-800 text-white rounded-md text-sm font-medium disabled:opacity-50 dark:bg-zinc-200 dark:text-zinc-900"
                >
                  Delete
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
    </AppShell>
  )
}
