'use client'

import { useEffect, useMemo, useState } from 'react'
import { useAuth, ClerkLoaded, UserButton } from "@clerk/clerk-react";
import Link from 'next/link'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface LeadRow {
  id: number
  name: string | null
  email: string
  company: string | null
  industry: string | null
  status: string
  touch_count: number
  email_opt_out: number
  last_contacted_at: string | null
  last_inbound_at: string | null
  created_at: string
  emails_sent: number
  responded: number
  meeting_booked: number
  campaigns: string
  last_outbound_status: string | null
  last_outbound_subject: string | null
  last_outbound_at: string | null
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

export default function LeadsPage() {
  const { isLoaded, userId, getToken } = useAuth()
  const [leads, setLeads] = useState<LeadRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')

  useEffect(() => {
    if (isLoaded && userId) {
      void loadLeads()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded, userId])

  const loadLeads = async () => {
    try {
      setLoading(true)
      setError('')
      const token = await getToken()
      const res = await fetch(`${API_BASE}/api/leads`, {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      if (!res.ok) throw new Error('Failed to load leads')
      const data = await res.json()
      setLeads(data.leads || [])
    } catch (err: any) {
      setError(err.message || 'Failed to load leads')
    } finally {
      setLoading(false)
    }
  }

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
            <Link href="/leads" className="text-sm font-medium text-zinc-900 dark:text-zinc-100">Leads</Link>
            <Link href="/drafts" className="text-sm text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100">Drafts</Link>
            <Link href="/staff" className="text-sm text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100">Staff</Link>
          </nav>
        </div>
        <ClerkLoaded>
          <UserButton />
        </ClerkLoaded>
      </header>

      <main className="flex-1 max-w-[92rem] mx-auto w-full p-8">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-6">
          <h2 className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">Lead Pipeline Status</h2>
          <div className="flex items-center gap-3">
            <input
              type="text"
              placeholder="Search by lead, campaign, email, status..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-80 px-3 py-2 border rounded-md dark:bg-zinc-800 dark:border-zinc-700"
            />
            <button
              onClick={() => void loadLeads()}
              className="px-3 py-2 border border-zinc-300 rounded-md text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              Refresh
            </button>
          </div>
        </div>

        {error && <div className="p-4 mb-4 text-red-700 bg-red-100 rounded-lg">{error}</div>}

        <div className="mb-3 text-sm text-zinc-500">
          Showing {filtered.length} of {leads.length} leads
        </div>

        <div className="bg-white border border-zinc-200 rounded-xl shadow-sm dark:bg-zinc-900 dark:border-zinc-800 overflow-hidden">
          {loading ? (
            <p className="p-6 text-zinc-500">Loading leads...</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm min-w-[1200px]">
                <thead className="bg-zinc-50 border-b border-zinc-200 dark:bg-zinc-800 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400">
                  <tr>
                    <th className="px-4 py-3 font-medium">Lead</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium">Campaign(s)</th>
                    <th className="px-4 py-3 font-medium">Emails Sent</th>
                    <th className="px-4 py-3 font-medium">Touches</th>
                    <th className="px-4 py-3 font-medium">Responded</th>
                    <th className="px-4 py-3 font-medium">Meeting</th>
                    <th className="px-4 py-3 font-medium">Last Outbound</th>
                    <th className="px-4 py-3 font-medium">Last Inbound</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                  {filtered.map((lead) => (
                    <tr key={lead.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/50 align-top">
                      <td className="px-4 py-3">
                        <div className="font-medium text-zinc-900 dark:text-zinc-100">
                          {lead.name || 'Unknown'} <span className="text-zinc-500">#{lead.id}</span>
                        </div>
                        <div className="text-xs text-zinc-500">{lead.email}</div>
                        <div className="text-xs text-zinc-500">{lead.company || 'No company'}{lead.industry ? ` • ${lead.industry}` : ''}</div>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${statusBadgeClass(lead.status)}`}>
                          {lead.status}
                        </span>
                        {lead.email_opt_out === 1 && (
                          <div className="text-xs text-rose-500 mt-1">Opted out</div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300">
                        {lead.campaigns || '-'}
                      </td>
                      <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300">{lead.emails_sent || 0}</td>
                      <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300">{lead.touch_count || 0}</td>
                      <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300">{lead.responded ? 'Yes' : 'No'}</td>
                      <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300">{lead.meeting_booked ? 'Booked' : '-'}</td>
                      <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300">
                        <div>{lead.last_outbound_status || '-'}</div>
                        <div className="text-xs text-zinc-500 truncate max-w-[220px]">{lead.last_outbound_subject || '-'}</div>
                        <div className="text-xs text-zinc-500">{lead.last_outbound_at || '-'}</div>
                      </td>
                      <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300">{lead.last_inbound_at || '-'}</td>
                    </tr>
                  ))}
                  {filtered.length === 0 && (
                    <tr>
                      <td colSpan={9} className="px-6 py-8 text-center text-zinc-500">
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
    </div>
  )
}
