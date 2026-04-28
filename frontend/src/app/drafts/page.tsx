'use client'

import { useEffect, useMemo, useState } from 'react'
import { useAuth, ClerkLoaded, UserButton } from "@clerk/clerk-react";
import Link from 'next/link'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Draft {
  id: number
  subject: string
  body: string
  created_at: string
  lead_name: string
  lead_email: string
  campaign_name: string
}

export default function DraftsPage() {
  const { isLoaded, userId, getToken } = useAuth()
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [busy, setBusy] = useState(false)
  const [stopFutureAttempts, setStopFutureAttempts] = useState(true)
  const [viewingDraft, setViewingDraft] = useState<Draft | null>(null)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return drafts
    return drafts.filter(d =>
      d.subject.toLowerCase().includes(q) ||
      d.body.toLowerCase().includes(q) ||
      d.lead_name.toLowerCase().includes(q) ||
      d.lead_email.toLowerCase().includes(q) ||
      d.campaign_name.toLowerCase().includes(q) ||
      String(d.id).includes(q)
    )
  }, [drafts, query])

  const visibleIds = useMemo(() => filtered.map(d => d.id), [filtered])
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every(id => selectedIds.includes(id))

  useEffect(() => {
    if (isLoaded && userId) {
      loadDrafts()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded, userId])

  const loadDrafts = async () => {
    try {
      setLoading(true)
      const token = await getToken()
      const res = await fetch(`${API_BASE}/api/drafts`, {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      if (!res.ok) throw new Error('Failed to load drafts')
      const data = await res.json()
      setDrafts(data.drafts || [])
      setSelectedIds([])
    } catch (err: any) {
      setError(err.message || 'Failed to load drafts')
    } finally {
      setLoading(false)
    }
  }

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

  const singleAction = async (draftId: number, approved: boolean) => {
    try {
      setBusy(true)
      const token = await getToken()
      const res = await fetch(`${API_BASE}/api/drafts/${draftId}/approve`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ approved })
      })
      if (!res.ok) throw new Error('Failed to process draft action')
      await loadDrafts()
    } catch (err: any) {
      alert(err.message || 'Action failed')
    } finally {
      setBusy(false)
    }
  }

  const batchAction = async (approved: boolean) => {
    if (selectedIds.length === 0) return
    try {
      setBusy(true)
      const token = await getToken()
      const res = await fetch(`${API_BASE}/api/drafts/batch-approve`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ draft_ids: selectedIds, approved })
      })
      if (!res.ok) throw new Error('Batch action failed')
      await loadDrafts()
    } catch (err: any) {
      alert(err.message || 'Batch action failed')
    } finally {
      setBusy(false)
    }
  }

  const singleDelete = async (draftId: number) => {
    if (!confirm(`Delete draft #${draftId}?`)) return
    try {
      setBusy(true)
      const token = await getToken()
      const res = await fetch(
        `${API_BASE}/api/drafts/${draftId}?stop_future_attempts=${stopFutureAttempts}`,
        {
          method: 'DELETE',
          headers: { 'Authorization': `Bearer ${token}` }
        }
      )
      if (!res.ok) throw new Error('Failed to delete draft')
      await loadDrafts()
    } catch (err: any) {
      alert(err.message || 'Delete failed')
    } finally {
      setBusy(false)
    }
  }

  const batchDelete = async () => {
    if (selectedIds.length === 0) return
    if (!confirm(`Delete ${selectedIds.length} selected draft(s)?`)) return
    try {
      setBusy(true)
      const token = await getToken()
      const res = await fetch(`${API_BASE}/api/drafts/batch-delete`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          draft_ids: selectedIds,
          stop_future_attempts: stopFutureAttempts
        })
      })
      if (!res.ok) throw new Error('Batch delete failed')
      await loadDrafts()
    } catch (err: any) {
      alert(err.message || 'Batch delete failed')
    } finally {
      setBusy(false)
    }
  }

  if (!isLoaded || !userId) {
    return <div className="flex items-center justify-center min-h-screen">Loading or unauthorized...</div>
  }

  return (
    <div className="flex flex-col min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <header className="flex items-center justify-between px-8 py-4 bg-white border-b border-zinc-200 dark:bg-zinc-900 dark:border-zinc-800">
        <div className="flex items-center gap-6">
          <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-50">Shiku SDR</h1>
          <nav className="flex gap-4">
            <Link href="/" className="text-sm text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100">Dashboard</Link>
            <Link href="/campaigns" className="text-sm text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100">Campaigns</Link>
            <Link href="/leads" className="text-sm text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100">Leads</Link>
            <Link href="/drafts" className="text-sm font-medium text-zinc-900 dark:text-zinc-100">Drafts</Link>
            <Link href="/staff" className="text-sm text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100">Staff</Link>
          </nav>
        </div>
        <ClerkLoaded>
          <UserButton />
        </ClerkLoaded>
      </header>

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

        {error && <div className="p-4 mb-4 text-red-700 bg-red-100 rounded-lg">{error}</div>}

        <div className="flex flex-wrap items-center gap-3 mb-4">
          <button
            disabled={busy || selectedIds.length === 0}
            onClick={() => batchAction(true)}
            className="px-4 py-2 bg-emerald-600 text-white rounded-md text-sm font-medium disabled:opacity-50"
          >
            Approve Selected ({selectedIds.length})
          </button>
          <button
            disabled={busy || selectedIds.length === 0}
            onClick={() => batchAction(false)}
            className="px-4 py-2 bg-rose-600 text-white rounded-md text-sm font-medium disabled:opacity-50"
          >
            Reject Selected ({selectedIds.length})
          </button>
          <button
            disabled={busy || selectedIds.length === 0}
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
                    </td>
                    <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300">
                      <div>{draft.lead_name}</div>
                      <div className="text-xs text-zinc-500">{draft.lead_email}</div>
                    </td>
                    <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300">{draft.campaign_name}</td>
                    <td className="px-4 py-3 text-zinc-500">{draft.created_at || '-'}</td>
                    <td className="px-4 py-3 text-right space-x-2">
                      <button
                        disabled={busy}
                        onClick={() => setViewingDraft(draft)}
                        className="px-3 py-1 bg-zinc-600 text-white rounded-md text-xs font-medium disabled:opacity-50"
                      >
                        View
                      </button>
                      <button
                        disabled={busy}
                        onClick={() => singleAction(draft.id, true)}
                        className="px-3 py-1 bg-emerald-600 text-white rounded-md text-xs font-medium disabled:opacity-50"
                      >
                        Approve
                      </button>
                      <button
                        disabled={busy}
                        onClick={() => singleAction(draft.id, false)}
                        className="px-3 py-1 bg-rose-600 text-white rounded-md text-xs font-medium disabled:opacity-50"
                      >
                        Reject
                      </button>
                      <button
                        disabled={busy}
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
                  <p className="text-sm text-zinc-600 dark:text-zinc-400">{viewingDraft.subject}</p>
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

              <div className="p-5 overflow-y-auto max-h-[58vh]">
                <div className="text-xs text-zinc-500 mb-3">Created: {viewingDraft.created_at || '-'}</div>
                <pre className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-800 dark:text-zinc-200 font-sans">
                  {viewingDraft.body}
                </pre>
              </div>

              <div className="p-5 border-t border-zinc-200 dark:border-zinc-800 flex flex-wrap gap-2 justify-end">
                <button
                  disabled={busy}
                  onClick={() => {
                    void singleAction(viewingDraft.id, true)
                    setViewingDraft(null)
                  }}
                  className="px-3 py-2 bg-emerald-600 text-white rounded-md text-sm font-medium disabled:opacity-50"
                >
                  Approve
                </button>
                <button
                  disabled={busy}
                  onClick={() => {
                    void singleAction(viewingDraft.id, false)
                    setViewingDraft(null)
                  }}
                  className="px-3 py-2 bg-rose-600 text-white rounded-md text-sm font-medium disabled:opacity-50"
                >
                  Reject
                </button>
                <button
                  disabled={busy}
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
    </div>
  )
}
