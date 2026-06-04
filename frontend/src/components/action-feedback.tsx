'use client'

export type ActionFeedbackState = {
  type: 'success' | 'error' | 'warning'
  message: string
} | null

const feedbackStyles = {
  success: 'border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-100',
  error: 'border-red-200 bg-red-50 text-red-900 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-100',
  warning: 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-100',
}

const dotStyles = {
  success: 'bg-emerald-500',
  error: 'bg-red-500',
  warning: 'bg-amber-500',
}

export function ActionFeedback({
  feedback,
  onDismiss,
  className = '',
}: {
  feedback: ActionFeedbackState
  onDismiss: () => void
  className?: string
}) {
  if (!feedback) return null

  return (
    <div
      role={feedback.type === 'error' ? 'alert' : 'status'}
      aria-live="polite"
      className={`flex items-start justify-between gap-3 rounded-lg border px-4 py-3 text-sm shadow-sm ${feedbackStyles[feedback.type]} ${className}`}
    >
      <div className="flex min-w-0 items-start gap-3">
        <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${dotStyles[feedback.type]}`} aria-hidden="true" />
        <p className="min-w-0 leading-5">{feedback.message}</p>
      </div>
      <button
        type="button"
        onClick={onDismiss}
        className="shrink-0 rounded px-2 py-1 text-xs font-medium hover:bg-black/5 dark:hover:bg-white/10"
        aria-label="Dismiss status message"
      >
        Dismiss
      </button>
    </div>
  )
}
