'use client'

import { ClerkLoaded, UserButton } from '@clerk/clerk-react'
import Link from 'next/link'
import { useState } from 'react'
import { PendingDraftsLink } from '@/components/pending-drafts-link'
import { OrganizationCapabilities, useTenantScope } from '@/components/tenant-scope'

type AppShellSection =
  | 'dashboard'
  | 'campaigns'
  | 'leads'
  | 'drafts'
  | 'staff'
  | 'plans'
  | 'usage'
  | 'mailboxes'
  | 'llm-credentials'
  | 'organization'
  | 'audit'

interface AppShellProps {
  active: AppShellSection
  children: React.ReactNode
}

type CapabilityKey = keyof OrganizationCapabilities

const navItems: Array<{ href: string; label: string; key: AppShellSection; capability?: CapabilityKey | CapabilityKey[] }> = [
  { href: '/', label: 'Dashboard', key: 'dashboard' },
  { href: '/campaigns', label: 'Campaigns', key: 'campaigns', capability: 'can_manage_campaigns' },
  { href: '/leads', label: 'Leads', key: 'leads', capability: 'can_manage_leads' },
  { href: '/drafts', label: 'Drafts', key: 'drafts', capability: 'can_review_drafts' },
  { href: '/staff', label: 'Staff', key: 'staff', capability: 'can_manage_staff' },
  { href: '/plans', label: 'Plans', key: 'plans', capability: ['can_manage_subscription_plans', 'can_choose_subscription_plan'] },
  { href: '/usage', label: 'Usage', key: 'usage' },
  { href: '/mailboxes', label: 'Mailboxes', key: 'mailboxes', capability: 'can_manage_mailboxes' },
  { href: '/llm-credentials', label: 'LLM Keys', key: 'llm-credentials', capability: 'can_manage_llm_credentials' },
  { href: '/organization', label: 'Organization', key: 'organization', capability: ['can_manage_organization', 'can_manage_users', 'can_create_organizations'] },
  { href: '/audit', label: 'Compliance', key: 'audit', capability: 'can_view_compliance' },
]

function navClass(active: boolean) {
  return active
    ? 'flex items-center justify-between rounded-md bg-zinc-900 px-3 py-2 text-sm font-medium text-white dark:bg-zinc-100 dark:text-zinc-900'
    : 'flex items-center justify-between rounded-md px-3 py-2 text-sm text-zinc-600 hover:bg-zinc-100 hover:text-zinc-950 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100'
}

export function AppShell({ active, children }: AppShellProps) {
  const { loading, organizations, selectedOrganizationId, selectedOrganization, setSelectedOrganization } = useTenantScope()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const capabilities = selectedOrganization?.capabilities
  const isLoadingTenantScope = loading && !selectedOrganization
  const visibleNavItems = isLoadingTenantScope ? [] : navItems.filter(item => {
    if (!item.capability) return true
    if (!capabilities) return false
    const required = Array.isArray(item.capability) ? item.capability : [item.capability]
    return required.some(capability => Boolean(capabilities[capability]))
  })

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
          {isLoadingTenantScope ? (
            <div className="space-y-2 px-3 py-2">
              <div className="h-4 w-32 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
              <div className="h-4 w-24 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
              <div className="h-4 w-28 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
            </div>
          ) : (
            visibleNavItems.map(item => (
              item.key === 'drafts' ? (
                <PendingDraftsLink key={item.key} active={active === item.key} className={navClass(active === item.key)} />
              ) : (
                <Link key={item.key} href={item.href} className={navClass(active === item.key)}>
                  <span>{item.label}</span>
                </Link>
              )
            ))
          )}
        </nav>
      </aside>

      <div className="lg:pl-64">
        <header className="sticky top-0 z-30 border-b border-zinc-200 bg-white/90 backdrop-blur dark:border-zinc-800 dark:bg-zinc-900/90">
          <div className="flex min-h-16 items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
            <div className="flex min-w-0 items-center gap-3">
              <button
                type="button"
                onClick={() => setMobileMenuOpen(open => !open)}
                className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-zinc-300 text-zinc-700 dark:border-zinc-700 dark:text-zinc-200 lg:hidden"
                aria-label="Toggle navigation"
                aria-expanded={mobileMenuOpen}
              >
                <span className="text-lg leading-none">{mobileMenuOpen ? '×' : '☰'}</span>
              </button>
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100">Shiku SDR</div>
                <div className="hidden truncate text-xs text-zinc-500 sm:block">Campaigns, approvals, scheduling, and compliance</div>
              </div>
            </div>
            <div className="flex min-w-0 items-center gap-2 sm:gap-3">
              {isLoadingTenantScope ? (
                <div className="h-8 w-32 animate-pulse rounded-md bg-zinc-200 dark:bg-zinc-800 sm:w-48" />
              ) : organizations.length > 0 && (
                <select
                  value={selectedOrganizationId || ''}
                  onChange={(event) => setSelectedOrganization(Number(event.target.value))}
                  className="max-w-32 rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-700 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 sm:max-w-48"
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
          </div>
          {mobileMenuOpen && (
            <nav className="grid gap-1 border-t border-zinc-200 p-3 dark:border-zinc-800 lg:hidden">
              {isLoadingTenantScope ? (
                <div className="space-y-2 px-3 py-2">
                  <div className="h-4 w-32 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
                  <div className="h-4 w-24 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
                  <div className="h-4 w-28 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
                </div>
              ) : (
                visibleNavItems.map(item => (
                  item.key === 'drafts' ? (
                    <PendingDraftsLink key={item.key} active={active === item.key} className={navClass(active === item.key)} />
                  ) : (
                    <Link
                      key={item.key}
                      href={item.href}
                      onClick={() => setMobileMenuOpen(false)}
                      className={navClass(active === item.key)}
                    >
                      <span>{item.label}</span>
                    </Link>
                  )
                ))
              )}
            </nav>
          )}
        </header>
        {children}
      </div>
    </div>
  )
}
