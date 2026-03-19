import { useCallback, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { uiLocale } from '../i18nFormat'

export type TimelineScrollbarProps = {
  currentRatio: number
  currentTs?: string | null
  firstTs?: string | null
  lastTs?: string | null
  /** 0 = Anfang (älteste), 1 = Ende (neueste). `commit` = Loslassen/Klick Ende → präzises Nachjustieren möglich. */
  onSeekRatio?: (ratio: number, phase: 'live' | 'commit') => void
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

function ratioFromClientY(trackEl: HTMLElement, clientY: number): number {
  const rect = trackEl.getBoundingClientRect()
  if (rect.height <= 0) return 0
  const y = clientY - rect.top
  return Math.max(0, Math.min(1, y / rect.height))
}

export default function TimelineScrollbar({
  currentRatio,
  currentTs = null,
  firstTs = null,
  lastTs = null,
  onSeekRatio,
}: TimelineScrollbarProps) {
  const { t, i18n } = useTranslation()
  const trackRef = useRef<HTMLDivElement>(null)
  const [dragRatio, setDragRatio] = useState<number | null>(null)

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

  const displayRatio = dragRatio ?? currentRatio

  const currentLabel = useMemo(() => {
    if (currentTs) return formatTimelineDate(currentTs, i18n.language, t('timeline.today'), t('timeline.yesterday'))
    return interpolateDate(displayRatio)
  }, [currentTs, displayRatio, interpolateDate, i18n.language, t])

  const handlePointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (!onSeekRatio || !trackRef.current) return
      e.preventDefault()
      const track = trackRef.current
      track.setPointerCapture(e.pointerId)
      const r = ratioFromClientY(track, e.clientY)
      setDragRatio(r)
      onSeekRatio(r, 'live')
    },
    [onSeekRatio],
  )

  const handlePointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!onSeekRatio || !trackRef.current || !trackRef.current.hasPointerCapture(e.pointerId)) return
      e.preventDefault()
      const r = ratioFromClientY(trackRef.current, e.clientY)
      setDragRatio(r)
      onSeekRatio(r, 'live')
    },
    [onSeekRatio],
  )

  const handlePointerUp = useCallback(
    (e: React.PointerEvent) => {
      if (trackRef.current?.hasPointerCapture(e.pointerId)) {
        trackRef.current.releasePointerCapture(e.pointerId)
      }
      if (onSeekRatio && trackRef.current) {
        const r = ratioFromClientY(trackRef.current, e.clientY)
        onSeekRatio(r, 'commit')
      }
      setDragRatio(null)
    },
    [onSeekRatio],
  )

  const interactive = Boolean(onSeekRatio)

  return (
    <div className="timelineScrollbarWrap">
      <div
        ref={trackRef}
        className={`timelineScrollbar ${interactive ? 'timelineScrollbarInteractive' : ''}`}
        title={t('timeline.title')}
        onPointerDown={interactive ? handlePointerDown : undefined}
        onPointerMove={interactive ? handlePointerMove : undefined}
        onPointerUp={interactive ? handlePointerUp : undefined}
        onPointerCancel={interactive ? handlePointerUp : undefined}
        role={interactive ? 'slider' : undefined}
        aria-valuemin={interactive ? 0 : undefined}
        aria-valuemax={interactive ? 1 : undefined}
        aria-valuenow={interactive ? Math.round(displayRatio * 1000) / 1000 : undefined}
        aria-orientation={interactive ? 'vertical' : undefined}
      >
        <div className="timelineTrack" />
        <div
          className="timelineThumb"
          style={{ top: `${displayRatio * 100}%` }}
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
            top: `${displayRatio * 100}%`,
            transform: displayRatio <= 0.05 ? 'translateY(0)' : displayRatio >= 0.95 ? 'translateY(-100%)' : 'translateY(-50%)',
          }}
        >
          {currentLabel}
        </div>
      )}
    </div>
  )
}
