'use client'

import { ClerkLoaded, UserButton } from '@clerk/clerk-react'
import Link from 'next/link'
import { PendingDraftsLink } from '@/components/pending-drafts-link'
import { useTenantScope } from '@/components/tenant-scope'

type AppShellSection =
  | 'dashboard'
  | 'campaigns'
  | 'leads'
  | 'drafts'
  | 'staff'
  | 'plans'
  | 'usage'
  | 'mailboxes'
  | 'organization'
  | 'audit'

interface AppShellProps {
  active: AppShellSection
  children: React.ReactNode
}

const navItems: Array<{ href: string; label: string; key: AppShellSection }> = [
  { href: '/', label: 'Dashboard', key: 'dashboard' },
  { href: '/campaigns', label: 'Campaigns', key: 'campaigns' },
  { href: '/leads', label: 'Leads', key: 'leads' },
  { href: '/drafts', label: 'Drafts', key: 'drafts' },
  { href: '/staff', label: 'Staff', key: 'staff' },
  { href: '/plans', label: 'Plans', key: 'plans' },
  { href: '/usage', label: 'Usage', key: 'usage' },
  { href: '/mailboxes', label: 'Mailboxes', key: 'mailboxes' },
  { href: '/organization', label: 'Organization', key: 'organization' },
  { href: '/audit', label: 'Compliance', key: 'audit' },
]

function navClass(active: boolean) {
  return active
    ? 'flex items-center justify-between rounded-md bg-zinc-900 px-3 py-2 text-sm font-medium text-white dark:bg-zinc-100 dark:text-zinc-900'
    : 'flex items-center justify-between rounded-md px-3 py-2 text-sm text-zinc-600 hover:bg-zinc-100 hover:text-zinc-950 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100'
}

export function AppShell({ active, children }: AppShellProps) {
  const { organizations, selectedOrganizationId, selectedOrganization, setSelectedOrganization } = useTenantScope()

  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-950 dark:bg-zinc-950 dark:text-zinc-50">
      <aside className="fixed inset-y-0 left-0 hidden w-64 border-r border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900 lg:flex lg:flex-col">
        <div className="flex h-16 items-center border-b border-zinc-200 px-5 dark:border-zinc-800">
          <div>
            <div className="text-lg font-semibold tracking-tight">Shiku SDR</div>
            <div className="text-xs text-zinc-500">Outreach operations</div>
          </div>
        </div>
        <nav className="flex-1 space-y-1 p-3">
          {navItems.map(item => (
            item.key === 'drafts' ? (
              <PendingDraftsLink key={item.key} active={active === item.key} className={navClass(active === item.key)} />
            ) : (
              <Link key={item.key} href={item.href} className={navClass(active === item.key)}>
                <span>{item.label}</span>
              </Link>
            )
          ))}
        </nav>
      </aside>

      <div className="lg:pl-64">
        <header className="sticky top-0 z-30 flex min-h-16 items-center justify-between border-b border-zinc-200 bg-white/90 px-4 backdrop-blur dark:border-zinc-800 dark:bg-zinc-900/90 sm:px-6 lg:px-8">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Shiku SDR</div>
            <div className="hidden text-xs text-zinc-500 sm:block">Campaigns, approvals, scheduling, and compliance</div>
          </div>
          <nav className="hidden items-center gap-3 md:flex lg:hidden">
            {navItems.slice(0, 5).map(item => (
              item.key === 'drafts' ? (
                <PendingDraftsLink key={item.key} active={active === item.key} />
              ) : (
                <Link
                  key={item.key}
                  href={item.href}
                  className={active === item.key ? 'text-sm font-medium text-zinc-900 dark:text-zinc-100' : 'text-sm text-zinc-500'}
                >
                  {item.label}
                </Link>
              )
            ))}
          </nav>
          <div className="flex items-center gap-3">
            {organizations.length > 0 && (
              <select
                value={selectedOrganizationId || ''}
                onChange={(event) => setSelectedOrganization(Number(event.target.value))}
                className="max-w-48 rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-700 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"
                aria-label="Active organization"
              >
                {organizations.map(org => (
                  <option key={org.id} value={org.id}>
                    {org.name} · {org.current_user_role}
                  </option>
                ))}
              </select>
            )}
            {selectedOrganization && (
              <span className="hidden rounded-md border border-zinc-200 px-2 py-1 text-xs text-zinc-500 dark:border-zinc-700 md:inline">
                {selectedOrganization.subscription?.plan?.name || 'No plan'} · {selectedOrganization.subscription?.effective_status || 'NONE'}
              </span>
            )}
            <ClerkLoaded>
              <UserButton />
            </ClerkLoaded>
          </div>
        </header>
        {children}
      </div>
    </div>
  )
}
