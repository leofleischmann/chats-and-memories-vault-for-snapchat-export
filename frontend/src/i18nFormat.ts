export function uiLocale(lang: string | undefined): string {
  const l = (lang || '').toLowerCase()
  if (l.startsWith('de')) return 'de-DE'
  return 'en-US'
}

export function formatNumber(lang: string | undefined, n: number | null | undefined): string {
  const value = n ?? 0
  return new Intl.NumberFormat(uiLocale(lang)).format(value)
}

export function formatDateShort(lang: string | undefined, iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return '—'
    return new Intl.DateTimeFormat(uiLocale(lang), { year: 'numeric', month: '2-digit', day: '2-digit' }).format(d)
  } catch {
    return '—'
  }
}

export function formatDateTime(lang: string | undefined, iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return '—'
    return new Intl.DateTimeFormat(uiLocale(lang), {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }).format(d)
  } catch {
    return '—'
  }
}

