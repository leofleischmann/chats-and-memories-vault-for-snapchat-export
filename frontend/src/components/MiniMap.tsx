import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'

export default function MiniMap({
  total,
  ordinals,
  onJump,
}: {
  total: number
  ordinals: number[]
  onJump: (ordinal: number) => void
}) {
  const { t } = useTranslation()
  const markers = useMemo(() => {
    const t = Math.max(1, total)
    return ordinals.map((o) => ({ o, y: (o / t) * 100 }))
  }, [ordinals, total])

  return (
    <div className="minimap" title={t('minimap.title')}>
      {markers.map((m, idx) => (
        <button
          key={`${m.o}-${idx}`}
          className="marker"
          style={{ top: `${m.y}%` }}
          onClick={() => onJump(m.o)}
        />
      ))}
    </div>
  )
}

