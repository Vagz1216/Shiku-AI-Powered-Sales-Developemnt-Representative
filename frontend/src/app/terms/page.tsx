import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Terms of Service | Shiku SDR',
  description: 'Terms of service for Shiku SDR.',
}

const effectiveDate = 'June 25, 2026'

export default function TermsPage() {
  return (
    <main className="min-h-screen bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-50">
      <div className="mx-auto max-w-4xl px-6 py-12">
        <div className="mb-10 border-b border-zinc-200 pb-6 dark:border-zinc-800">
          <p className="text-sm font-medium text-zinc-500">Shiku SDR</p>
          <h1 className="mt-2 text-3xl font-bold tracking-normal">Terms of Service</h1>
          <p className="mt-3 text-sm text-zinc-500">Effective date: {effectiveDate}</p>
        </div>

        <div className="space-y-8 text-sm leading-6 text-zinc-700 dark:text-zinc-300">
          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">Agreement</h2>
            <p className="mt-2">
              These Terms of Service govern access to and use of Shiku SDR, a sales outreach, email drafting,
              scheduling, sending, and inbound reply-monitoring application. By using Shiku SDR, you agree to these
              terms on behalf of yourself and, where applicable, the organization you represent.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">Use Of The Service</h2>
            <p className="mt-2">
              You may use Shiku SDR only for lawful business outreach, lead management, and reply-monitoring activities.
              You are responsible for ensuring that your campaigns, contact lists, messages, and mailbox use comply
              with applicable laws, provider policies, anti-spam rules, and privacy requirements.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">User And Organization Responsibilities</h2>
            <ul className="mt-3 list-disc space-y-2 pl-5">
              <li>You must provide accurate account and organization information.</li>
              <li>You must keep login credentials, API keys, and mailbox credentials secure.</li>
              <li>You must have permission to connect any mailbox, domain, lead list, or third-party service used with Shiku SDR.</li>
              <li>You must review AI-generated drafts and automated actions according to your organization approval settings.</li>
              <li>You are responsible for the content, timing, recipients, and legal basis of emails sent through connected mailboxes.</li>
            </ul>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">Email And Mailbox Connections</h2>
            <p className="mt-2">
              Shiku SDR may allow users to connect SMTP/IMAP, API-based, Google, or Microsoft mailboxes. By connecting
              a mailbox, you authorize Shiku SDR to use that mailbox for the features you enable, including sending
              approved messages, polling or receiving inbound replies, classifying reply intent, and creating drafts or
              follow-up actions.
            </p>
            <p className="mt-3">
              Email providers may reject, throttle, suspend, or block messages based on their own policies. Shiku SDR
              does not guarantee inbox placement, delivery, provider acceptance, or avoidance of spam classification.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">Acceptable Use</h2>
            <p className="mt-2">You may not use Shiku SDR to:</p>
            <ul className="mt-3 list-disc space-y-2 pl-5">
              <li>Send spam, phishing, fraudulent, deceptive, or unlawful communications.</li>
              <li>Contact people without a lawful basis or in violation of applicable consent, unsubscribe, or opt-out requirements.</li>
              <li>Misrepresent your identity, organization, domain, product, pricing, or relationship with a recipient.</li>
              <li>Upload or process data that you do not have the right to use.</li>
              <li>Bypass provider sending limits, abuse prevention systems, security controls, or access restrictions.</li>
              <li>Use AI outputs without appropriate human review where review is required by your organization, law, or provider policy.</li>
            </ul>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">AI-Generated Content</h2>
            <p className="mt-2">
              Shiku SDR may generate draft emails, reply suggestions, classifications, summaries, and recommendations
              using AI systems. AI outputs may be incomplete, inaccurate, or inappropriate for a particular recipient.
              You are responsible for reviewing and approving externally visible messages before they are sent, unless
              your organization has explicitly configured automatic approval.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">Plans, Limits, And Availability</h2>
            <p className="mt-2">
              Access to features may depend on your organization plan, configuration, provider availability, usage
              limits, and connected services. We may update features, limits, pricing, or availability from time to
              time. We may suspend or limit access if we detect abuse, security risk, unpaid usage, or violations of
              these terms.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">Data And Privacy</h2>
            <p className="mt-2">
              Our handling of personal data and mailbox data is described in our{' '}
              <a className="font-medium text-zinc-950 underline dark:text-zinc-50" href="/privacy">
                Privacy Policy
              </a>
              . By using Shiku SDR, you confirm that you have the rights and permissions needed to provide data to the
              service and to connect any mailbox or third-party account.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">Disclaimers</h2>
            <p className="mt-2">
              Shiku SDR is provided on an as-is and as-available basis. We do not guarantee uninterrupted operation,
              error-free output, email deliverability, lead accuracy, revenue results, or that AI-generated content will
              satisfy your legal, compliance, or business requirements.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">Limitation Of Liability</h2>
            <p className="mt-2">
              To the maximum extent permitted by law, Shiku SDR and its operators will not be liable for indirect,
              incidental, special, consequential, exemplary, or punitive damages, or for lost profits, lost revenue,
              lost data, email provider action, spam classification, or business interruption arising from use of the
              service.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">Changes To These Terms</h2>
            <p className="mt-2">
              We may update these terms from time to time. Updated terms will be posted on this page with a new
              effective date. Continued use of Shiku SDR after changes become effective means you accept the updated
              terms.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-zinc-950 dark:text-zinc-50">Contact</h2>
            <p className="mt-2">
              For questions about these terms, contact us at{' '}
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
