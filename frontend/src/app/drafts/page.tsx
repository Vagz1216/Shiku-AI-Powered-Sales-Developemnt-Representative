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
  lead_name: string
  lead_email: string
  campaign_name: string
  attachments: DraftAttachment[]
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
    if (!q) return drafts
    return drafts.filter(d =>
      d.subject.toLowerCase().includes(q) ||
      d.body.toLowerCase().includes(q) ||
      d.lead_name.toLowerCase().includes(q) ||
      d.lead_email.toLowerCase().includes(q) ||
      d.campaign_name.toLowerCase().includes(q) ||
      (d.attachments || []).some(a => a.filename.toLowerCase().includes(q)) ||
      String(d.id).includes(q)
    )
  }, [drafts, query])

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

  if (!isLoaded || !userId) {
    return <div className="flex items-center justify-center min-h-screen">Loading or unauthorized...</div>
  }

  return (
    <AppShell active="drafts">
      <main className="flex-1 max-w-7xl mx-auto w-full p-8">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-6">
          <h2 className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">Draft Approvals</h2>
          <div className="flex items-center gap-3">
            <input
              type="text"
              placeholder="Search by id, lead, campaign, subject..."
              value={query}
              onChange={e => setQuery(e.target.value)}
              className="w-80 px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700"
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

        <div className="bg-white border border-zinc-200 rounded-xl shadow-sm dark:bg-zinc-900 dark:border-zinc-800 overflow-hidden">
          {loading ? (
            <p className="p-6 text-zinc-500">Loading drafts...</p>
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="bg-zinc-50 border-b border-zinc-200 dark:bg-zinc-800 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400">
                <tr>
                  <th className="px-4 py-3 font-medium w-10"></th>
                  <th className="px-4 py-3 font-medium">Draft</th>
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
                    <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300">
                      <div>{draft.lead_name}</div>
                      <div className="text-xs text-zinc-500">{draft.lead_email}</div>
                    </td>
                    <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300">{draft.campaign_name}</td>
                    <td className="px-4 py-3 text-zinc-500">{formatTimestamp(draft.created_at, selectedOrganization?.timezone)}</td>
                    <td className="px-4 py-3 text-right space-x-2">
                      <button
                        disabled={busy || !canReviewDrafts}
                        onClick={() => openDraft(draft)}
                        className="px-3 py-1 bg-zinc-600 text-white rounded-md text-xs font-medium disabled:opacity-50"
                      >
                        Review
                      </button>
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
                    <td colSpan={6} className="px-6 py-8 text-center text-zinc-500">
                      No pending drafts found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>

        {viewingDraft && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
            <div className="w-full max-w-4xl max-h-[90vh] overflow-hidden rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 shadow-2xl">
              <div className="flex items-start justify-between gap-4 p-5 border-b border-zinc-200 dark:border-zinc-800">
                <div>
                  <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
                    Draft #{viewingDraft.id}
                  </h3>
                  <p className="text-sm text-zinc-600 dark:text-zinc-400">Review and edit before approval</p>
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

                <label className="block">
                  <span className="block text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-1">Subject</span>
                  <input
                    type="text"
                    value={editSubject}
                    onChange={e => setEditSubject(e.target.value)}
                    className="w-full px-3 py-2 border rounded-md text-sm dark:bg-zinc-800 dark:border-zinc-700"
                  />
                </label>

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
                <input
                  type="datetime-local"
                  value={scheduledSendAt}
                  onChange={(e) => setScheduledSendAt(e.target.value)}
                  className="px-3 py-2 border rounded-md text-sm dark:bg-zinc-800 dark:border-zinc-700"
                />
                <button
                  disabled={busy || savingEdit}
                  onClick={() => void saveDraftEdits()}
                  className="px-3 py-2 border border-zinc-300 rounded-md text-sm font-medium disabled:opacity-50 dark:border-zinc-700"
                >
                  {savingEdit ? 'Saving...' : 'Save Changes'}
                </button>
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
