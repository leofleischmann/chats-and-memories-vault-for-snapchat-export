import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { uiLocale } from '../i18nFormat'

export type TimelineScrollbarProps = {
  totalCount: number
  currentRatio: number
  currentTs?: string | null
  hitOrdinals: number[]
  onJumpToOrdinal: (ordinal: number) => void
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
  totalCount,
  currentRatio,
  currentTs = null,
  hitOrdinals,
  onJumpToOrdinal,
  firstTs = null,
  lastTs = null,
}: TimelineScrollbarProps) {
  const { t, i18n } = useTranslation()
  const [isDragging, setIsDragging] = useState(false)
  const [dragRatio, setDragRatio] = useState<number | null>(null)
  const trackRef = useRef<HTMLDivElement>(null)
  const lastOrdinalRef = useRef(0)

  const ratioFromY = useCallback(
    (clientY: number) => {
      const track = trackRef.current
      if (!track || totalCount === 0) return 0
      const rect = track.getBoundingClientRect()
      return Math.max(0, Math.min(1, (clientY - rect.top) / rect.height))
    },
    [totalCount],
  )

  // ratio 0 = top = oldest (ordinal 0), ratio 1 = bottom = newest (ordinal max)
  const ordinalFromRatio = useCallback(
    (ratio: number) => Math.round(ratio * Math.max(0, totalCount - 1)),
    [totalCount],
  )

  const handleTrackClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (totalCount === 0 || isDragging) return
      const r = ratioFromY(e.clientY)
      onJumpToOrdinal(ordinalFromRatio(r))
    },
    [totalCount, isDragging, onJumpToOrdinal, ratioFromY, ordinalFromRatio],
  )

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      e.stopPropagation()
      const r = ratioFromY(e.clientY)
      lastOrdinalRef.current = ordinalFromRatio(r)
      setDragRatio(r)
      setIsDragging(true)
    },
    [ratioFromY, ordinalFromRatio],
  )

  useEffect(() => {
    if (!isDragging) return
    const onMove = (e: MouseEvent) => {
      const r = ratioFromY(e.clientY)
      lastOrdinalRef.current = ordinalFromRatio(r)
      setDragRatio(r)
    }
    const onUp = () => {
      setIsDragging(false)
      setDragRatio(null)
      onJumpToOrdinal(lastOrdinalRef.current)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [isDragging, onJumpToOrdinal, ratioFromY, ordinalFromRatio])

  const tMinus1 = Math.max(1, totalCount - 1)
  const thumbRatio = dragRatio ?? currentRatio

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
    return interpolateDate(thumbRatio)
  }, [currentTs, thumbRatio, interpolateDate, i18n.language, t])

  const dragLabel = useMemo(() => {
    return interpolateDate(thumbRatio)
  }, [thumbRatio, interpolateDate])

  return (
    <div className="timelineScrollbarWrap">
      <div className="timelineScrollbar" ref={trackRef} onClick={handleTrackClick} title={t('timeline.title')}>
        <div className="timelineTrack" />
        {hitOrdinals.map((o, idx) => (
          <div
            key={idx}
            className="timelineMarker"
            style={{ top: `${(o / tMinus1) * 100}%` }}
            onClick={(e) => {
              e.stopPropagation()
              onJumpToOrdinal(o)
            }}
            title={t('timeline.hitTitle', { n: o })}
          />
        ))}
        <div
          className="timelineThumb"
          style={{ top: `${thumbRatio * 100}%` }}
          onMouseDown={handleMouseDown}
        />
        {isDragging && (
          <div className="timelineTooltip" style={{ top: `${thumbRatio * 100}%` }}>
            {dragLabel != null && <span className="timelineTooltipDate">{dragLabel}</span>}
          </div>
        )}
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
      {timelineLabels != null && currentLabel != null && !isDragging && (
        <div
          className="timelineCurrentLabel"
          style={{
            top: `${thumbRatio * 100}%`,
            transform: thumbRatio <= 0.05 ? 'translateY(0)' : thumbRatio >= 0.95 ? 'translateY(-100%)' : 'translateY(-50%)',
          }}
        >
          {currentLabel}
        </div>
      )}
    </div>
  )
}
