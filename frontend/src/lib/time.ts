export const DEFAULT_TIME_ZONE = 'Africa/Nairobi'

export const TIME_ZONE_OPTIONS = [
  'Africa/Nairobi',
  'Africa/Kampala',
  'Africa/Dar_es_Salaam',
  'Africa/Kigali',
  'Africa/Lagos',
  'Europe/London',
  'America/New_York',
  'America/Los_Angeles',
  'UTC',
]

const TIME_ZONE_ALIASES: Record<string, string> = {
  'Africa/NIAROBI': DEFAULT_TIME_ZONE,
  'Africa/Niarobi': DEFAULT_TIME_ZONE,
  'africa/niarobi': DEFAULT_TIME_ZONE,
  'africa/nairobi': DEFAULT_TIME_ZONE,
}

const OFFSETLESS_TIMESTAMP_RE = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/
const HAS_TIME_ZONE_RE = /(Z|[+-]\d{2}:?\d{2})$/i

export function normalizeTimeZone(timeZone?: string | null) {
  const raw = (timeZone || DEFAULT_TIME_ZONE).trim()
  const resolved = TIME_ZONE_ALIASES[raw] || raw
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: resolved }).format(new Date(0))
    return resolved
  } catch {
    return DEFAULT_TIME_ZONE
  }
}

export function parseBackendTimestamp(value: string | Date | null | undefined) {
  if (!value) return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value

  const raw = value.trim()
  if (!raw) return null

  const normalized = OFFSETLESS_TIMESTAMP_RE.test(raw) && !HAS_TIME_ZONE_RE.test(raw)
    ? `${raw.replace(' ', 'T')}Z`
    : raw

  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatTimestamp(
  value: string | Date | null | undefined,
  timeZone?: string | null,
  options: Intl.DateTimeFormatOptions = { dateStyle: 'medium', timeStyle: 'short' },
) {
  const date = parseBackendTimestamp(value)
  if (!date) return '-'
  return new Intl.DateTimeFormat('en-KE', {
    ...options,
    timeZone: normalizeTimeZone(timeZone),
  }).format(date)
}

export function formatDate(value: string | Date | null | undefined, timeZone?: string | null) {
  return formatTimestamp(value, timeZone, { dateStyle: 'medium' })
}

export function formatTime(value: string | Date | null | undefined, timeZone?: string | null) {
  return formatTimestamp(value, timeZone, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

function timeZoneParts(date: Date, timeZone?: string | null) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: normalizeTimeZone(timeZone),
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).formatToParts(date)

  return Object.fromEntries(parts.map(part => [part.type, part.value]))
}

function timeZoneOffsetMs(date: Date, timeZone?: string | null) {
  const parts = timeZoneParts(date, timeZone)
  const asUtc = Date.UTC(
    Number(parts.year),
    Number(parts.month) - 1,
    Number(parts.day),
    Number(parts.hour),
    Number(parts.minute),
    Number(parts.second),
  )
  return asUtc - date.getTime()
}

export function toDatetimeLocal(value: string | Date | null | undefined, timeZone?: string | null) {
  const date = parseBackendTimestamp(value)
  if (!date) return ''
  const parts = timeZoneParts(date, timeZone)
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`
}

export function zonedLocalToIso(value: string, timeZone?: string | null) {
  const [datePart, timePart] = value.split('T')
  if (!datePart || !timePart) return null

  const [year, month, day] = datePart.split('-').map(Number)
  const [hour, minute] = timePart.split(':').map(Number)
  if (![year, month, day, hour, minute].every(Number.isFinite)) return null

  const naiveUtc = Date.UTC(year, month - 1, day, hour, minute, 0)
  const offset = timeZoneOffsetMs(new Date(naiveUtc), timeZone)
  return new Date(naiveUtc - offset).toISOString()
}
