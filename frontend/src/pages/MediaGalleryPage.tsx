import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiGet, mediaUrl } from '../api'
import type { MediaFile, MediaChat } from '../api'
import { formatNumber } from '../i18nFormat'

const PAGE_SIZE = 60

export default function MediaGalleryPage() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const [files, setFiles] = useState<MediaFile[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)

  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [chatFilter, setChatFilter] = useState('')
  const [assignmentFilter, setAssignmentFilter] = useState<'all' | 'assigned' | 'unassigned'>('assigned')

  const [mediaChats, setMediaChats] = useState<MediaChat[]>([])
  const [selected, setSelected] = useState<MediaFile | null>(null)

  useEffect(() => {
    apiGet<{ chats: MediaChat[] }>('/api/media/chats')
      .then((r) => setMediaChats(r.chats))
      .catch(() => {})
  }, [])

  const load = useCallback(() => {
    setLoading(true)
    const params = new URLSearchParams()
    params.set('offset', String(offset))
    params.set('limit', String(PAGE_SIZE))
    if (dateFrom) params.set('date_from', dateFrom)
    if (dateTo) params.set('date_to', dateTo)
    if (typeFilter) params.set('media_type', typeFilter)
    if (chatFilter) params.set('chat_id', chatFilter)
    params.set('assigned_only', assignmentFilter === 'assigned' ? 'true' : 'false')
    if (assignmentFilter === 'unassigned') params.set('unassigned_only', 'true')

    apiGet<{ total: number; files: MediaFile[] }>(`/api/media?${params}`)
      .then((r) => {
        setFiles(r.files)
        setTotal(r.total)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [offset, dateFrom, dateTo, typeFilter, chatFilter, assignmentFilter])

  useEffect(() => { load() }, [load])

  function applyFilter() {
    setOffset(0)
  }

  function resetFilters() {
    setDateFrom('')
    setDateTo('')
    setTypeFilter('')
    setChatFilter('')
    setAssignmentFilter('assigned')
    setOffset(0)
  }

  function goToMessage(f: MediaFile) {
    if (f.chat_id && f.message_id) {
      navigate(`/chat/${encodeURIComponent(f.chat_id)}?m=${encodeURIComponent(f.message_id)}`)
    }
  }

  const totalPages = Math.ceil(total / PAGE_SIZE)
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1
  const isAudio = (f: MediaFile) => f.msg_type === 'NOTE' || f.media_type === 'audio'
  const isVideo = (f: MediaFile) => !isAudio(f) && f.media_type === 'video'

  return (
    <div className="mediaGalleryPage">
      <h2>{t('media.title')}</h2>
      <p className="muted" style={{ marginBottom: 12 }}>
        {formatNumber(i18n.language, total)} {t('media.filesLabel')}
        {' '}
        {chatFilter
          ? t('media.inChat', { chat: mediaChats.find((c) => c.chat_id === chatFilter)?.title || chatFilter })
          : t('media.totalSuffix')}
      </p>

      <div className="mediaFilters">
        <label>
          {t('media.from')}
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </label>
        <label>
          {t('media.to')}
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </label>
        <label>
          {t('media.type')}
          <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
            <option value="">{t('media.types.all')}</option>
            <option value="image">{t('media.types.images')}</option>
            <option value="video">{t('media.types.videos')}</option>
            <option value="audio">{t('media.types.audio')}</option>
          </select>
        </label>
        <label>
          {t('media.chat')}
          <select value={chatFilter} onChange={(e) => setChatFilter(e.target.value)}>
            <option value="">{t('media.chatsAll')}</option>
            {mediaChats.map((c) => (
              <option key={c.chat_id} value={c.chat_id}>
                {c.title} ({c.media_count})
              </option>
            ))}
          </select>
        </label>
        <label>
          {t('media.assignment')}
          <select
            value={assignmentFilter}
            onChange={(e) => { setAssignmentFilter(e.target.value as 'all' | 'assigned' | 'unassigned'); setOffset(0) }}
          >
            <option value="all">{t('media.assignmentAll')}</option>
            <option value="assigned">{t('media.assignmentAssigned')}</option>
            <option value="unassigned">{t('media.assignmentUnassigned')}</option>
          </select>
        </label>
        <button className="btn" onClick={applyFilter}>{t('media.filter')}</button>
        {(dateFrom || dateTo || typeFilter || chatFilter || assignmentFilter !== 'assigned') && (
          <button className="btn btnGhost" onClick={resetFilters}>{t('media.reset')}</button>
        )}
      </div>

      {loading ? (
        <p className="muted">{t('common.loading')}</p>
      ) : (
        <>
          <div className="mediaGrid">
            {files.map((f) => (
              <div
                key={f.filename}
                className="mediaCard"
                onClick={() => setSelected(f)}
              >
                {isAudio(f) ? (
                  <div className="audioCardPlaceholder">
                    <span className="audioIcon">🎤</span>
                    <span className="audioLabel">{t('media.voiceMessage')}</span>
                  </div>
                ) : isVideo(f) ? (
                  <>
                    <video src={mediaUrl(f.filename)} preload="metadata" />
                    <span className="videoIndicator">VIDEO</span>
                  </>
                ) : (
                  <img src={mediaUrl(f.filename)} alt="" loading="lazy" />
                )}
                <div className="mediaCardInfo">
                  {f.chat_title && (
                    <span className="mediaCardChat" title={f.chat_title}>{f.chat_title}</span>
                  )}
                  <span className="mediaCardDate">
                    {f.ts_utc ? f.ts_utc.slice(0, 16).replace('T', ' ') : f.file_date || ''}
                  </span>
                </div>
              </div>
            ))}
          </div>

          {totalPages > 1 && (
            <div className="mediaPagination">
              <button
                className="btn"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                {t('media.prev')}
              </button>
              <span className="muted">
                {t('media.page', { current: currentPage, total: totalPages })}
              </span>
              <button
                className="btn"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                {t('media.next')}
              </button>
            </div>
          )}
        </>
      )}

      {selected && (
        <div className="lightboxOverlay" onClick={() => setSelected(null)}>
          <div className="lightboxContent" onClick={(e) => e.stopPropagation()}>
            {isAudio(selected) ? (
              <div className="lightboxAudioWrap">
                <span className="lightboxAudioIcon">🎤</span>
                <audio
                  src={mediaUrl(selected.filename)}
                  controls
                  autoPlay
                  style={{ width: '100%', maxWidth: 400 }}
                />
              </div>
            ) : isVideo(selected) ? (
              <video
                src={mediaUrl(selected.filename)}
                className="lightboxMedia"
                controls
                autoPlay
              />
            ) : (
              <img src={mediaUrl(selected.filename)} className="lightboxMedia" alt="" />
            )}
            <div className="lightboxInfo">
              <div className="lightboxMeta">
                {selected.chat_title && (
                  <span className="lightboxChat">{selected.chat_title}</span>
                )}
                {selected.sender && (
                  <span className="lightboxSender">{t('media.by', { sender: selected.sender })}</span>
                )}
                <span className="lightboxDate">
                  {selected.ts_utc ? selected.ts_utc.slice(0, 16).replace('T', ' ') : selected.file_date || ''}
                </span>
              </div>
              <div className="lightboxActions">
                {selected.chat_id && selected.message_id && (
                  <button className="btn btnPrimary" onClick={() => goToMessage(selected)}>
                    {t('media.showInChat')}
                  </button>
                )}
                <button className="btn btnGhost" onClick={() => setSelected(null)}>
                  {t('common.close')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
