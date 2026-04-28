'use client'

import { useEffect, useMemo, useState } from 'react'
import { useAuth, ClerkLoaded, UserButton } from "@clerk/clerk-react";
import Link from 'next/link'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Staff {
  id: number
  name: string
  email: string
  timezone: string | null
  availability: string | null
}

interface Campaign {
  id: number
  name: string
}

interface CampaignStaffRow {
  id: number
  name: string
  email: string
  timezone: string | null
  assigned: number
}

export default function StaffPage() {
  const { isLoaded, userId, getToken } = useAuth()
  const [staff, setStaff] = useState<Staff[]>([])
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [selectedCampaignId, setSelectedCampaignId] = useState<number | null>(null)
  const [campaignStaff, setCampaignStaff] = useState<CampaignStaffRow[]>([])
  const [selectedStaffIds, setSelectedStaffIds] = useState<number[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')

  const [formData, setFormData] = useState({
    id: 0,
    name: '',
    email: '',
    timezone: '',
    availability: '',
  })
  const [editing, setEditing] = useState(false)

  useEffect(() => {
    if (isLoaded && userId) {
      void loadInitial()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded, userId])

  const loadInitial = async () => {
    try {
      setLoading(true)
      setError('')
      const token = await getToken()
      const [staffRes, campaignsRes] = await Promise.all([
        fetch(`${API_BASE}/api/staff`, { headers: { 'Authorization': `Bearer ${token}` } }),
        fetch(`${API_BASE}/api/campaigns?active_only=false`, { headers: { 'Authorization': `Bearer ${token}` } }),
      ])
      if (!staffRes.ok) throw new Error('Failed to load staff')
      if (!campaignsRes.ok) throw new Error('Failed to load campaigns')
      const staffData = await staffRes.json()
      const campaignData = await campaignsRes.json()
      setStaff(staffData.staff || [])
      const campList = campaignData.campaigns || []
      setCampaigns(campList)
      if (campList.length > 0) {
        const firstId = campList[0].id
        setSelectedCampaignId(firstId)
        await loadCampaignStaff(firstId)
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load data')
    } finally {
      setLoading(false)
    }
  }

  const loadStaffOnly = async () => {
    const token = await getToken()
    const res = await fetch(`${API_BASE}/api/staff`, { headers: { 'Authorization': `Bearer ${token}` } })
    if (!res.ok) throw new Error('Failed to load staff')
    const data = await res.json()
    setStaff(data.staff || [])
  }

  const loadCampaignStaff = async (campaignId: number) => {
    const token = await getToken()
    const res = await fetch(`${API_BASE}/api/campaigns/${campaignId}/staff`, {
      headers: { 'Authorization': `Bearer ${token}` }
    })
    if (!res.ok) throw new Error('Failed to load campaign staff')
    const data = await res.json()
    const rows = data.staff || []
    setCampaignStaff(rows)
    setSelectedStaffIds(rows.filter((s: CampaignStaffRow) => !!s.assigned).map((s: CampaignStaffRow) => s.id))
  }

  const resetForm = () => {
    setEditing(false)
    setFormData({ id: 0, name: '', email: '', timezone: '', availability: '' })
  }

  const submitStaff = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      setSaving(true)
      const token = await getToken()
      const payload = {
        name: formData.name,
        email: formData.email,
        timezone: formData.timezone || null,
        availability: formData.availability || null,
        dummy_slots: null
      }
      const url = editing ? `${API_BASE}/api/staff/${formData.id}` : `${API_BASE}/api/staff`
      const method = editing ? 'PUT' : 'POST'
      const res = await fetch(url, {
        method,
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      })
      if (!res.ok) throw new Error('Failed to save staff')
      resetForm()
      await loadStaffOnly()
      if (selectedCampaignId) await loadCampaignStaff(selectedCampaignId)
    } catch (err: any) {
      alert(err.message || 'Failed to save staff')
    } finally {
      setSaving(false)
    }
  }

  const editStaff = (s: Staff) => {
    setEditing(true)
    setFormData({
      id: s.id,
      name: s.name,
      email: s.email,
      timezone: s.timezone || '',
      availability: s.availability || '',
    })
  }

  const removeStaff = async (staffId: number) => {
    if (!confirm('Delete this staff member?')) return
    try {
      setSaving(true)
      const token = await getToken()
      const res = await fetch(`${API_BASE}/api/staff/${staffId}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      })
      if (!res.ok) throw new Error('Failed to delete staff')
      await loadStaffOnly()
      if (selectedCampaignId) await loadCampaignStaff(selectedCampaignId)
    } catch (err: any) {
      alert(err.message || 'Failed to delete staff')
    } finally {
      setSaving(false)
    }
  }

  const toggleAssigned = (staffId: number) => {
    setSelectedStaffIds((prev) => (
      prev.includes(staffId) ? prev.filter(id => id !== staffId) : [...prev, staffId]
    ))
  }

  const saveAssignments = async () => {
    if (!selectedCampaignId) return
    try {
      setSaving(true)
      const token = await getToken()
      const res = await fetch(`${API_BASE}/api/campaigns/${selectedCampaignId}/staff`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ staff_ids: selectedStaffIds })
      })
      if (!res.ok) throw new Error('Failed to save assignments')
      await loadCampaignStaff(selectedCampaignId)
    } catch (err: any) {
      alert(err.message || 'Failed to save assignments')
    } finally {
      setSaving(false)
    }
  }

  const filteredStaff = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return staff
    return staff.filter((s) =>
      s.name.toLowerCase().includes(q) ||
      s.email.toLowerCase().includes(q) ||
      (s.timezone || '').toLowerCase().includes(q)
    )
  }, [staff, query])

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
            <Link href="/drafts" className="text-sm text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100">Drafts</Link>
            <Link href="/staff" className="text-sm font-medium text-zinc-900 dark:text-zinc-100">Staff</Link>
          </nav>
        </div>
        <ClerkLoaded>
          <UserButton />
        </ClerkLoaded>
      </header>

      <main className="flex-1 max-w-7xl mx-auto w-full p-8 space-y-6">
        <h2 className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">Campaign Staff Routing</h2>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Assign staff per campaign so meeting notifications only go to the right people.
        </p>
        {error && <div className="p-4 text-red-700 bg-red-100 rounded-lg">{error}</div>}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <section className="bg-white border border-zinc-200 rounded-xl shadow-sm dark:bg-zinc-900 dark:border-zinc-800 p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Staff Directory</h3>
              <input
                type="text"
                placeholder="Search staff..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="w-48 px-3 py-2 border rounded-md text-sm dark:bg-zinc-800 dark:border-zinc-700"
              />
            </div>

            <form onSubmit={submitStaff} className="space-y-3 mb-5">
              <div className="grid grid-cols-2 gap-3">
                <input
                  required
                  placeholder="Name"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="px-3 py-2 border rounded-md text-sm dark:bg-zinc-800 dark:border-zinc-700"
                />
                <input
                  required
                  type="email"
                  placeholder="Email"
                  value={formData.email}
                  onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                  className="px-3 py-2 border rounded-md text-sm dark:bg-zinc-800 dark:border-zinc-700"
                />
                <input
                  placeholder="Timezone (optional)"
                  value={formData.timezone}
                  onChange={(e) => setFormData({ ...formData, timezone: e.target.value })}
                  className="px-3 py-2 border rounded-md text-sm dark:bg-zinc-800 dark:border-zinc-700"
                />
                <input
                  placeholder='Availability JSON (optional)'
                  value={formData.availability}
                  onChange={(e) => setFormData({ ...formData, availability: e.target.value })}
                  className="px-3 py-2 border rounded-md text-sm dark:bg-zinc-800 dark:border-zinc-700"
                />
              </div>
              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={saving}
                  className="px-3 py-2 bg-zinc-900 text-white rounded-md text-sm font-medium disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900"
                >
                  {editing ? 'Update Staff' : 'Add Staff'}
                </button>
                {editing && (
                  <button
                    type="button"
                    onClick={resetForm}
                    className="px-3 py-2 border border-zinc-300 rounded-md text-sm dark:border-zinc-700"
                  >
                    Cancel
                  </button>
                )}
              </div>
            </form>

            <div className="max-h-[360px] overflow-auto border border-zinc-200 dark:border-zinc-800 rounded-md">
              {loading ? (
                <p className="p-4 text-sm text-zinc-500">Loading staff...</p>
              ) : (
                <table className="w-full text-sm">
                  <thead className="bg-zinc-50 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">Name</th>
                      <th className="px-3 py-2 text-left font-medium">Email</th>
                      <th className="px-3 py-2 text-right font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                    {filteredStaff.map((s) => (
                      <tr key={s.id}>
                        <td className="px-3 py-2">
                          <div>{s.name}</div>
                          <div className="text-xs text-zinc-500">{s.timezone || '-'}</div>
                        </td>
                        <td className="px-3 py-2">{s.email}</td>
                        <td className="px-3 py-2 text-right">
                          <button onClick={() => editStaff(s)} className="text-blue-600 hover:text-blue-800 dark:text-blue-400 mr-3">Edit</button>
                          <button onClick={() => void removeStaff(s.id)} className="text-red-600 hover:text-red-800 dark:text-red-400">Delete</button>
                        </td>
                      </tr>
                    ))}
                    {filteredStaff.length === 0 && (
                      <tr>
                        <td colSpan={3} className="px-3 py-4 text-center text-zinc-500">No staff found.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              )}
            </div>
          </section>

          <section className="bg-white border border-zinc-200 rounded-xl shadow-sm dark:bg-zinc-900 dark:border-zinc-800 p-5">
            <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100 mb-4">Campaign Assignment</h3>
            <div className="mb-4">
              <label className="block text-sm text-zinc-700 dark:text-zinc-300 mb-1">Campaign</label>
              <select
                value={selectedCampaignId ?? ''}
                onChange={async (e) => {
                  const campaignId = Number(e.target.value)
                  setSelectedCampaignId(campaignId)
                  await loadCampaignStaff(campaignId)
                }}
                className="w-full px-3 py-2 border rounded-md text-sm dark:bg-zinc-800 dark:border-zinc-700"
              >
                {campaigns.map(c => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>

            <div className="max-h-[390px] overflow-auto border border-zinc-200 dark:border-zinc-800 rounded-md p-2">
              {campaignStaff.map((s) => (
                <label key={s.id} className="flex items-start gap-3 p-2 rounded hover:bg-zinc-50 dark:hover:bg-zinc-800/60">
                  <input
                    type="checkbox"
                    checked={selectedStaffIds.includes(s.id)}
                    onChange={() => toggleAssigned(s.id)}
                    className="mt-1"
                  />
                  <div className="text-sm">
                    <div className="font-medium text-zinc-900 dark:text-zinc-100">{s.name}</div>
                    <div className="text-zinc-600 dark:text-zinc-400">{s.email}</div>
                    <div className="text-xs text-zinc-500">{s.timezone || '-'}</div>
                  </div>
                </label>
              ))}
              {campaignStaff.length === 0 && (
                <p className="p-3 text-sm text-zinc-500">No staff available.</p>
              )}
            </div>
            <div className="mt-4 flex justify-end">
              <button
                disabled={saving || !selectedCampaignId}
                onClick={() => void saveAssignments()}
                className="px-4 py-2 bg-zinc-900 text-white rounded-md text-sm font-medium disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900"
              >
                Save Campaign Staff
              </button>
            </div>
          </section>
        </div>
      </main>
    </div>
  )
}
