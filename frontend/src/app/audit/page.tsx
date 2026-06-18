'use client'

import { useCallback, useEffect, useState } from 'react'
import { useAuth } from '@clerk/clerk-react'
import { AppShell } from '@/components/app-shell'
import { useTenantScope } from '@/components/tenant-scope'
import { fetchWithAuthRetry } from '@/lib/auth-fetch'
import { formatTimestamp } from '@/lib/time'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface AuditEvent {
  id: number
  type: string
  payload: unknown
  metadata: unknown
  created_at: string
}

interface AuditStream {
  name: string
  storage: string
  access: string
  contains: string[]
  notes: string
}

interface RoleAccess {
  role: string
  scope: string
  can_access: string[]
}

function formatJson(value: unknown) {
  if (value == null || value === '') return '-'
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

function getErrorMessage(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback
}

export default function AuditPage() {
  const { isLoaded, userId, getToken } = useAuth()
  const { selectedOrganizationId, selectedOrganization } = useTenantScope()
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [streams, setStreams] = useState<AuditStream[]>([])
  const [roles, setRoles] = useState<RoleAccess[]>([])
  const [eventType, setEventType] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [eventsForbidden, setEventsForbidden] = useState(false)

  const authedFetch = useCallback(async (url: string, init: RequestInit = {}) => {
    return fetchWithAuthRetry(getToken, url, init)
  }, [getToken])

  const loadStreams = useCallback(async () => {
    const res = await authedFetch(`${API_BASE}/api/audit/streams`)
    if (!res.ok) throw new Error('Failed to load audit stream metadata')
    const data = await res.json() as { streams?: AuditStream[]; roles?: RoleAccess[] }
    setStreams(data.streams || [])
    setRoles(data.roles || [])
  }, [authedFetch])

  const loadEvents = useCallback(async () => {
    const url = new URL(`${API_BASE}/api/audit/events`)
    url.searchParams.set('limit', '100')
    if (selectedOrganizationId) url.searchParams.set('organization_id', String(selectedOrganizationId))
    if (eventType.trim()) url.searchParams.set('event_type', eventType.trim())
    const res = await authedFetch(url.toString())
    if (res.status === 403) {
      setEventsForbidden(true)
      setEvents([])
      return
    }
    if (!res.ok) throw new Error('Failed to load audit events')
    const data = await res.json() as { events?: AuditEvent[] }
    setEventsForbidden(false)
    setEvents(data.events || [])
  }, [authedFetch, eventType, selectedOrganizationId])

  const loadAll = useCallback(async () => {
    try {
      setLoading(true)
      setError('')
      await loadStreams()
      await loadEvents()
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load compliance data'))
    } finally {
      setLoading(false)
    }
  }, [loadEvents, loadStreams])

  useEffect(() => {
    if (isLoaded && userId && selectedOrganizationId) {
      const timer = window.setTimeout(() => {
        void loadAll()
      }, 0)
      return () => window.clearTimeout(timer)
    }
  }, [isLoaded, userId, selectedOrganizationId, loadAll])

  if (!isLoaded || !userId) {
    return <div className="flex min-h-screen items-center justify-center">Loading or unauthorized...</div>
  }

  return (
    <AppShell active="audit">
      <main className="mx-auto w-full max-w-[96rem] p-6 lg:p-8">
        <div className="mb-6 flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Compliance & Audit</h1>
            <p className="mt-1 text-sm text-zinc-500">
              Durable business events, operational log streams, and role access boundaries.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <input
              value={eventType}
              onChange={(e) => setEventType(e.target.value)}
              placeholder="Filter event type"
              className="w-64 rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
            />
            <button
              onClick={() => void loadAll()}
              className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white dark:bg-zinc-100 dark:text-zinc-900"
            >
              Refresh
            </button>
          </div>
        </div>

        {error && <div className="mb-4 rounded-md bg-rose-100 p-4 text-sm text-rose-700">{error}</div>}

        <section className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-3">
          {streams.map(stream => (
            <div key={stream.name} className="rounded-lg border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
              <div className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{stream.name}</div>
              <div className="mt-1 text-xs text-zinc-500">{stream.storage}</div>
              <div className="mt-3 text-xs font-medium uppercase tracking-wide text-zinc-500">Access</div>
              <div className="mt-1 text-sm text-zinc-700 dark:text-zinc-300">{stream.access}</div>
              <div className="mt-3 flex flex-wrap gap-1">
                {stream.contains.map(item => (
                  <span key={item} className="rounded border border-zinc-200 px-2 py-0.5 text-[11px] text-zinc-600 dark:border-zinc-700 dark:text-zinc-300">
                    {item}
                  </span>
                ))}
              </div>
              <p className="mt-3 text-xs leading-relaxed text-zinc-500">{stream.notes}</p>
            </div>
          ))}
        </section>

        <section className="mb-6 rounded-lg border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <div className="border-b border-zinc-200 px-4 py-3 font-semibold dark:border-zinc-800">Role Access</div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead className="bg-zinc-50 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                <tr>
                  <th className="px-4 py-3 font-medium">Role</th>
                  <th className="px-4 py-3 font-medium">Scope</th>
                  <th className="px-4 py-3 font-medium">Can Access</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                {roles.map(row => (
                  <tr key={row.role}>
                    <td className="px-4 py-3 font-medium">{row.role}</td>
                    <td className="px-4 py-3 text-zinc-600 dark:text-zinc-300">{row.scope}</td>
                    <td className="px-4 py-3 text-zinc-600 dark:text-zinc-300">{row.can_access.join(', ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="rounded-lg border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <div className="flex items-center justify-between gap-3 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
            <div>
              <div className="font-semibold">Durable Audit Events</div>
              <div className="text-xs text-zinc-500">Platform-wide business event trail. Restricted to system owners.</div>
            </div>
            {eventsForbidden && (
              <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
                System owner only
              </span>
            )}
          </div>
          {loading ? (
            <p className="p-6 text-sm text-zinc-500">Loading audit data...</p>
          ) : eventsForbidden ? (
            <p className="p-6 text-sm text-zinc-500">
              Your current role can view the compliance stream map, but raw platform-wide audit events are restricted.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[980px] text-left text-sm">
                <thead className="bg-zinc-50 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                  <tr>
                    <th className="px-4 py-3 font-medium">Time</th>
                    <th className="px-4 py-3 font-medium">Type</th>
                    <th className="px-4 py-3 font-medium">Payload</th>
                    <th className="px-4 py-3 font-medium">Metadata</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                  {events.map(event => (
                    <tr key={event.id} className="align-top">
                      <td className="px-4 py-3 text-zinc-500">{formatTimestamp(event.created_at, selectedOrganization?.timezone)}</td>
                      <td className="px-4 py-3 font-medium">{event.type}</td>
                      <td className="px-4 py-3">
                        <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded bg-zinc-50 p-2 text-xs dark:bg-zinc-950">
                          {formatJson(event.payload)}
                        </pre>
                      </td>
                      <td className="px-4 py-3">
                        <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded bg-zinc-50 p-2 text-xs dark:bg-zinc-950">
                          {formatJson(event.metadata)}
                        </pre>
                      </td>
                    </tr>
                  ))}
                  {events.length === 0 && (
                    <tr>
                      <td colSpan={4} className="px-6 py-8 text-center text-zinc-500">No audit events found.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </AppShell>
  )
}
