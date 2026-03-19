import { useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { uiLocale } from '../i18nFormat'

export type TimelineScrollbarProps = {
  currentRatio: number
  currentTs?: string | null
  firstTs?: string | null
  lastTs?: string | null
}

function formatTimelineDate(iso: string, lang: string, todayLabel: string, yesterdayLabel: string): string {
  const d = new Date(iso)
  const now = new Date()
  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
  if (sameDay(d, now)) return todayLabel
  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  if (sameDay(d, yesterday)) return yesterdayLabel
  return d.toLocaleDateString(uiLocale(lang), { day: '2-digit', month: '2-digit', year: '2-digit' })
}

export default function TimelineScrollbar({
  currentRatio,
  currentTs = null,
  firstTs = null,
  lastTs = null,
}: TimelineScrollbarProps) {
  const { t, i18n } = useTranslation()

  const interpolateDate = useCallback(
    (ratio: number): string | null => {
      if (!firstTs || !lastTs) return null
      const first = new Date(firstTs).getTime()
      const last = new Date(lastTs).getTime()
      if (first >= last) return null
      const ts = new Date(first + ratio * (last - first))
      return formatTimelineDate(ts.toISOString(), i18n.language, t('timeline.today'), t('timeline.yesterday'))
    },
    [firstTs, lastTs, i18n.language, t],
  )

  const timelineLabels = useMemo(() => {
    if (!firstTs || !lastTs) return null
    const ratios = [0, 0.25, 0.5, 0.75, 1]
    return ratios.map((r) => ({
      ratio: r,
      label: interpolateDate(r) ?? '',
    }))
  }, [firstTs, lastTs, interpolateDate])

  const currentLabel = useMemo(() => {
    if (currentTs) return formatTimelineDate(currentTs, i18n.language, t('timeline.today'), t('timeline.yesterday'))
    return interpolateDate(currentRatio)
  }, [currentTs, currentRatio, interpolateDate, i18n.language, t])

  return (
    <div className="timelineScrollbarWrap">
      <div className="timelineScrollbar" title={t('timeline.title')}>
        <div className="timelineTrack" />
        <div
          className="timelineThumb"
          style={{ top: `${currentRatio * 100}%` }}
        />
      </div>
      {timelineLabels != null && (
        <div className="timelineLabels" aria-hidden>
          {timelineLabels.map(({ ratio, label }) => {
            const isFirst = ratio === 0
            const isLast = ratio === 1
            const transform = isFirst ? 'translateY(0)' : isLast ? 'translateY(-100%)' : 'translateY(-50%)'
            return (
              <div
                key={ratio}
                className="timelineLabel"
                style={{ top: `${ratio * 100}%`, transform }}
              >
                {label}
              </div>
            )
          })}
        </div>
      )}
      {timelineLabels != null && currentLabel != null && (
        <div
          className="timelineCurrentLabel"
          style={{
            top: `${currentRatio * 100}%`,
            transform: currentRatio <= 0.05 ? 'translateY(0)' : currentRatio >= 0.95 ? 'translateY(-100%)' : 'translateY(-50%)',
          }}
        >
          {currentLabel}
        </div>
      )}
    </div>
  )
}
