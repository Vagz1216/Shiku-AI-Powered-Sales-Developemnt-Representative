import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Privacy Policy | Shiku SDR',
  description: 'Privacy policy for Shiku SDR.',
}

const effectiveDate = 'June 25, 2026'

export default function PrivacyPage() {
  return (
    <main className="min-h-screen bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-50">
      <div className="mx-auto max-w-4xl px-6 py-12">
        <div className="mb-10 border-b border-zinc-200 pb-6 dark:border-zinc-800">
          <p className="text-sm font-medium text-zinc-500">Shiku SDR</p>
          <h1 className="mt-2 text-3xl font-bold tracking-normal">Privacy Policy</h1>
          <p className="mt-3 text-sm text-zinc-500">Effective date: {effectiveDate}</p>
        </div>

        <div className="space-y-8 text-sm leading-6 text-zinc-700 dark:text-zinc-300">
          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">Overview</h2>
            <p className="mt-2">
              Shiku SDR is a sales outreach and reply-monitoring application. This policy explains how we collect,
              use, store, and protect information when organizations and their users connect mailboxes, manage
              campaigns, draft outreach, send approved emails, and monitor inbound replies.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">Information We Collect</h2>
            <p className="mt-2">We may collect and process the following information:</p>
            <ul className="mt-3 list-disc space-y-2 pl-5">
              <li>Account information, such as name, email address, organization, role, and authentication identifiers.</li>
              <li>Organization data, such as subscription plan, team members, campaigns, leads, staff availability, and usage records.</li>
              <li>Lead and campaign data entered or imported by users, including names, email addresses, company details, outreach context, and campaign settings.</li>
              <li>Email mailbox connection data, including provider type, email address, connection status, token expiry, and encrypted credentials or OAuth tokens where applicable.</li>
              <li>Email content needed to provide the service, including outbound drafts, sent email metadata, inbound replies, attachments metadata, message IDs, thread IDs, subjects, and message bodies.</li>
              <li>Operational data, such as audit logs, API request logs, delivery status, scheduler activity, provider errors, and security events.</li>
            </ul>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">Google User Data</h2>
            <p className="mt-2">
              If you connect a Google Gmail or Google Workspace mailbox, Shiku SDR requests access only for features
              needed to send approved outreach and monitor inbound replies for your organization. Depending on the
              scopes granted, Shiku SDR may access your email address, basic profile information, email sending
              capability, unread message metadata, message content required for reply classification, and message
              state needed to mark processed messages.
            </p>
            <p className="mt-3">
              We use Google user data only to provide user-facing mailbox features in Shiku SDR. We do not sell Google
              user data. We do not use Google user data for advertising. We do not allow humans to read email content
              unless required to provide support, investigate abuse or security incidents, comply with law, or when an
              authorized user in your organization has access to that data through the product.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">How We Use Information</h2>
            <ul className="mt-3 list-disc space-y-2 pl-5">
              <li>To authenticate users and enforce organization-level access controls.</li>
              <li>To create, review, approve, schedule, and send outreach emails.</li>
              <li>To monitor connected inboxes for replies and classify reply intent.</li>
              <li>To create drafts or follow-up actions based on campaign settings and human approval rules.</li>
              <li>To provide tenant administration, usage reporting, audit logs, and support.</li>
              <li>To detect abuse, prevent unauthorized access, debug failures, and maintain service reliability.</li>
            </ul>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">AI Processing</h2>
            <p className="mt-2">
              Shiku SDR uses AI systems to draft outreach, evaluate message safety, classify inbound replies, and
              generate suggested responses. Email and lead context may be sent to configured AI providers only as
              needed to perform these functions. We apply human approval and safety checks for externally visible
              actions such as sending emails, according to your organization settings.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">Storage And Security</h2>
            <p className="mt-2">
              We use administrative, technical, and organizational safeguards designed to protect user and organization
              data. Mailbox passwords, API keys, OAuth access tokens, and OAuth refresh tokens are stored encrypted or
              otherwise protected by application secrets. Access to tenant data is controlled by organization membership
              and role permissions.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">Sharing And Service Providers</h2>
            <p className="mt-2">
              We may share data with service providers that help operate Shiku SDR, including authentication providers,
              email providers, cloud hosting providers, database providers, monitoring providers, and AI providers.
              These providers process information only as needed to provide their services to us and to you.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">Data Retention And Deletion</h2>
            <p className="mt-2">
              We retain information for as long as needed to provide the service, meet legal obligations, resolve
              disputes, enforce agreements, and maintain security. Organization administrators may request deletion of
              mailbox connections, campaign data, lead data, or organization data, subject to legal and operational
              retention requirements.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">Revoking Mailbox Access</h2>
            <p className="mt-2">
              You can revoke connected mailbox access by removing the mailbox connection in Shiku SDR or by revoking
              the application from your email provider account settings. After revocation, Shiku SDR will no longer be
              able to send mail or monitor replies for that mailbox unless access is granted again.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">Contact</h2>
            <p className="mt-2">
              For privacy questions, data deletion requests, or security concerns, contact us at{' '}
              <a className="font-medium text-zinc-950 underline dark:text-zinc-50" href="mailto:info@markethacks.co.ke">
                info@markethacks.co.ke
              </a>
              .
            </p>
          </section>
        </div>
      </div>
    </main>
  )
}
