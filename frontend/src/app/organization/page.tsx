'use client'

import { useAuth } from '@clerk/clerk-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { AppShell } from '@/components/app-shell'
import { TenantOrganization, notifyOrganizationChanged, useTenantScope } from '@/components/tenant-scope'
import { DEFAULT_TIME_ZONE, TIME_ZONE_OPTIONS, normalizeTimeZone } from '@/lib/time'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface OrganizationUser {
  id: number
  email: string
  name: string | null
  platform_role: string
  organization_id: number
  role: string
  status: string
  created_at: string
}

const roleDescriptions: Record<string, string> = {
  org_admin: 'Manages organization settings, users, mailboxes, and all SDR workflows.',
  sales_manager: 'Runs outreach, manages staff, campaigns, leads, drafts, and usage.',
  sales_user: 'Works campaigns, leads, and draft review without tenant administration.',
  viewer: 'Read-only access where routes allow.',
  system_owner: 'Platform owner with access to every organization and system audit events.',
}

const roleOptions = ['org_admin', 'sales_manager', 'sales_user', 'viewer']
const statusOptions = ['ACTIVE', 'INVITED', 'DISABLED']

function getErrorMessage(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback
}

export default function OrganizationPage() {
  const { isLoaded, userId, getToken } = useAuth()
  const {
    loading,
    organizations,
    selectedOrganization,
    selectedOrganizationId,
    setSelectedOrganization,
    reloadOrganizations,
  } = useTenantScope()
  const [members, setMembers] = useState<OrganizationUser[]>([])
  const [memberEmail, setMemberEmail] = useState('')
  const [memberRole, setMemberRole] = useState('sales_manager')
  const [memberStatus, setMemberStatus] = useState('ACTIVE')
  const [orgName, setOrgName] = useState('')
  const [orgSlug, setOrgSlug] = useState('')
  const [ownerEmail, setOwnerEmail] = useState('')
  const [timezone, setTimezone] = useState(DEFAULT_TIME_ZONE)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const currentRole = selectedOrganization?.current_user_role || 'viewer'
  const capabilities = selectedOrganization?.capabilities
  const canManageUsers = !!capabilities?.can_manage_users
  const canCreateOrganizations = organizations.some(org => org.current_user_role === 'system_owner')

  const authedFetch = useCallback(async (url: string, init: RequestInit = {}) => {
    const token = await getToken()
    const headers = new Headers(init.headers)
    headers.set('Authorization', `Bearer ${token}`)
    return fetch(url, { ...init, headers })
  }, [getToken])

  const loadMembers = useCallback(async () => {
    if (!selectedOrganizationId) return
    setError('')
    try {
      const res = await authedFetch(`${API_BASE}/api/organizations/${selectedOrganizationId}/users`)
      if (res.status === 403) {
        setMembers([])
        return
      }
      if (!res.ok) throw new Error('Failed to load organization members')
      const data = await res.json() as { users?: OrganizationUser[] }
      setMembers(data.users || [])
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load organization members'))
    }
  }, [authedFetch, selectedOrganizationId])

  useEffect(() => {
    if (isLoaded && userId) {
      const timer = window.setTimeout(() => {
        void loadMembers()
      }, 0)
      return () => window.clearTimeout(timer)
    }
  }, [isLoaded, userId, loadMembers])

  const createOrganization = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const res = await authedFetch(`${API_BASE}/api/organizations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: orgName,
          slug: orgSlug || null,
          owner_email: ownerEmail || null,
          timezone,
        }),
      })
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed to create organization')
      const data = await res.json() as { organization: TenantOrganization }
      await reloadOrganizations()
      setSelectedOrganization(data.organization.id)
      notifyOrganizationChanged(data.organization.id)
      setOrgName('')
      setOrgSlug('')
      setOwnerEmail('')
      setNotice(`Created ${data.organization.name}.`)
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to create organization'))
    } finally {
      setBusy(false)
    }
  }

  const saveTimezone = async (nextTimezone: string) => {
    if (!selectedOrganizationId || !capabilities?.can_manage_organization) return
    const normalizedTimezone = normalizeTimeZone(nextTimezone)
    setTimezone(normalizedTimezone)
    setError('')
    setNotice('')
    try {
      const res = await authedFetch(`${API_BASE}/api/organizations/${selectedOrganizationId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ timezone: normalizedTimezone }),
      })
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed to update timezone')
      await reloadOrganizations()
      setNotice('Organization timezone updated.')
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to update timezone'))
    }
  }

  const upsertMember = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedOrganizationId) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const res = await authedFetch(`${API_BASE}/api/organizations/${selectedOrganizationId}/users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: memberEmail, role: memberRole, status: memberStatus }),
      })
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed to save member')
      setMemberEmail('')
      setMemberRole('sales_manager')
      setMemberStatus('ACTIVE')
      setNotice('Member saved. They can sign in with Clerk using that email.')
      await loadMembers()
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to save member'))
    } finally {
      setBusy(false)
    }
  }

  const roleRows = useMemo(() => {
    const platformRole = organizations.some(org => org.current_user_role === 'system_owner') ? ['system_owner'] : []
    return [...platformRole, ...roleOptions]
  }, [organizations])

  if (!isLoaded || !userId || loading) {
    return <div className="flex min-h-screen items-center justify-center">Loading or unauthorized...</div>
  }

  return (
    <AppShell active="organization">
      <main className="mx-auto w-full max-w-[96rem] p-6 lg:p-8">
        <div className="mb-6 flex flex-col gap-2">
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Organization</h1>
          <p className="text-sm text-zinc-500">
            Select a tenant, manage users, and verify role boundaries before shared testing.
          </p>
        </div>

        {error && <div className="mb-4 rounded-md bg-rose-100 p-4 text-sm text-rose-700">{error}</div>}
        {notice && <div className="mb-4 rounded-md bg-emerald-100 p-4 text-sm text-emerald-800">{notice}</div>}

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
          <section className="space-y-4">
            <div className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
              <h2 className="text-base font-semibold">Active Tenant</h2>
              <select
                value={selectedOrganizationId || ''}
                onChange={(event) => setSelectedOrganization(Number(event.target.value))}
                className="mt-3 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
              >
                {organizations.map(org => (
                  <option key={org.id} value={org.id}>{org.name} · {org.current_user_role}</option>
                ))}
              </select>
              <div className="mt-4 space-y-1 text-sm text-zinc-600 dark:text-zinc-300">
                <div>Name: {selectedOrganization?.name || '-'}</div>
                <div>Slug: {selectedOrganization?.slug || '-'}</div>
                <div>Status: {selectedOrganization?.status || '-'}</div>
                <div>Your role: {currentRole}</div>
              </div>
            </div>

            <div className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
              <h2 className="text-base font-semibold">Timezone</h2>
              <select
                value={normalizeTimeZone(selectedOrganization?.timezone || timezone)}
                disabled={!capabilities?.can_manage_organization}
                onChange={(event) => void saveTimezone(event.target.value)}
                className="mt-3 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-800"
              >
                {TIME_ZONE_OPTIONS.map(zone => (
                  <option key={zone} value={zone}>{zone}</option>
                ))}
              </select>
            </div>

            {canCreateOrganizations && (
              <form onSubmit={createOrganization} className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
                <h2 className="text-base font-semibold">Create Tenant</h2>
                <div className="mt-4 space-y-3">
                  <input value={orgName} onChange={e => setOrgName(e.target.value)} required placeholder="Organization name" className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                  <input value={orgSlug} onChange={e => setOrgSlug(e.target.value)} placeholder="Slug, optional" className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                  <input value={ownerEmail} onChange={e => setOwnerEmail(e.target.value)} placeholder="Owner email" className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                  <select value={timezone} onChange={e => setTimezone(normalizeTimeZone(e.target.value))} className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800">
                    {TIME_ZONE_OPTIONS.map(zone => <option key={zone} value={zone}>{zone}</option>)}
                  </select>
                  <button disabled={busy} className="w-full rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900">
                    Create Organization
                  </button>
                </div>
              </form>
            )}
          </section>

          <section className="space-y-6">
            <div className="rounded-lg border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
              <div className="border-b border-zinc-200 px-5 py-3 font-semibold dark:border-zinc-800">Members</div>
              {canManageUsers && (
                <form onSubmit={upsertMember} className="grid grid-cols-1 gap-3 border-b border-zinc-200 p-5 dark:border-zinc-800 md:grid-cols-[minmax(0,1fr)_160px_140px_120px]">
                  <input value={memberEmail} onChange={e => setMemberEmail(e.target.value)} required type="email" placeholder="friend@example.com" className="rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800" />
                  <select value={memberRole} onChange={e => setMemberRole(e.target.value)} className="rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800">
                    {roleOptions.map(role => <option key={role} value={role}>{role}</option>)}
                  </select>
                  <select value={memberStatus} onChange={e => setMemberStatus(e.target.value)} className="rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800">
                    {statusOptions.map(status => <option key={status} value={status}>{status}</option>)}
                  </select>
                  <button disabled={busy} className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900">Save</button>
                </form>
              )}
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-left text-sm">
                  <thead className="bg-zinc-50 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                    <tr>
                      <th className="px-4 py-3 font-medium">Email</th>
                      <th className="px-4 py-3 font-medium">Name</th>
                      <th className="px-4 py-3 font-medium">Role</th>
                      <th className="px-4 py-3 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                    {members.map(member => (
                      <tr key={`${member.organization_id}-${member.id}`}>
                        <td className="px-4 py-3">{member.email}</td>
                        <td className="px-4 py-3 text-zinc-600 dark:text-zinc-300">{member.name || '-'}</td>
                        <td className="px-4 py-3">{member.role}</td>
                        <td className="px-4 py-3">{member.status}</td>
                      </tr>
                    ))}
                    {members.length === 0 && (
                      <tr><td colSpan={4} className="px-6 py-8 text-center text-zinc-500">No visible members.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="rounded-lg border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
              <div className="border-b border-zinc-200 px-5 py-3 font-semibold dark:border-zinc-800">Role Guide</div>
              <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
                {roleRows.map(role => (
                  <div key={role} className="grid grid-cols-1 gap-2 px-5 py-4 md:grid-cols-[180px_minmax(0,1fr)]">
                    <div className="font-medium">{role}</div>
                    <div className="text-sm text-zinc-600 dark:text-zinc-300">{roleDescriptions[role]}</div>
                  </div>
                ))}
              </div>
            </div>
          </section>
        </div>
      </main>
    </AppShell>
  )
}
