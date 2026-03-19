import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams, useNavigate } from 'react-router-dom'
import { Virtuoso } from 'react-virtuoso'
import type { VirtuosoHandle } from 'react-virtuoso'
import { useTranslation } from 'react-i18next'
import { apiGet, apiPost, mediaUrl } from '../api'
import type { Chat, Message } from '../api'
import TimelineScrollbar from '../components/TimelineScrollbar'

const CustomScroller = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  (props, ref) => <div {...props} ref={ref} className="chatScrollerHideBar" />,
)
CustomScroller.displayName = 'CustomScroller'

/** Backend erlaubt bis 100_000 pro Request; mehrere Requests bei sehr großen Chats */
const FETCH_CHUNK = 100_000

async function fetchAllMessagesForChat(chatId: string): Promise<{ messages: Message[]; chat: Chat }> {
  let offset = 0
  let all: Message[] = []
  let chat: Chat | null = null

  for (;;) {
    const r = await apiGet<{ messages: Message[]; chat: Chat }>(
      `/api/chats/${encodeURIComponent(chatId)}/messages?offset=${offset}&limit=${FETCH_CHUNK}`,
    )
    chat = r.chat
    if (r.messages.length === 0) break
    if (offset === 0) {
      all = r.messages
    } else {
      all = [...r.messages, ...all]
    }
    offset += r.messages.length
    if (all.length >= chat.message_count) break
  }

  if (!chat) throw new Error('Chat not found')
  return { messages: all, chat }
}

/** Virtuoso schätzt Zeilenhöhen; nach dem Scrollen ins DOM zentrieren. */
function refineScrollToMessageElement(opts: { ordinal?: number; messageId?: string }) {
  const sel =
    opts.messageId != null && opts.messageId !== ''
      ? `[data-message-id="${CSS.escape(opts.messageId)}"]`
      : opts.ordinal != null
        ? `[data-ordinal="${opts.ordinal}"]`
        : null
  if (!sel) return

  const run = () => {
    const el = document.querySelector(sel!)
    el?.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'auto' })
  }

  requestAnimationFrame(() => requestAnimationFrame(run))
  setTimeout(run, 80)
  setTimeout(run, 250)
}

export default function ChatPage() {
  const { t } = useTranslation()
  const { chatId } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()

  const [chat, setChat] = useState<Chat | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const [searchQ, setSearchQ] = useState('')
  const [searchHits, setSearchHits] = useState<any[]>([])
  const [visibleRange, setVisibleRange] = useState<{ startIndex: number; endIndex: number }>({ startIndex: 0, endIndex: 0 })

  const [highlightedMessageId, setHighlightedMessageId] = useState<string | null>(null)

  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null)

  const virtuosoRef = useRef<VirtuosoHandle>(null)

  const messageOrdinalParam = searchParams.get('message')
  const messageIdParam = searchParams.get('m')
  const targetOrdinal = messageOrdinalParam != null ? parseInt(messageOrdinalParam, 10) : null
  const isValidOrdinal = targetOrdinal != null && !Number.isNaN(targetOrdinal) && targetOrdinal >= 1

  const scrollToMessageIndex = useCallback(
    (
      dataIndex: number,
      opts?: { messageId?: string; ordinal?: number },
      refineDom = true,
    ) => {
      if (dataIndex < 0 || !virtuosoRef.current) return
      virtuosoRef.current.scrollToIndex({
        index: dataIndex,
        align: 'center',
        behavior: 'auto',
      })
      if (refineDom) {
        refineScrollToMessageElement({
          messageId: opts?.messageId,
          ordinal: opts?.ordinal,
        })
      }
    },
    [],
  )

  const seekChatRatio = useCallback(
    (ratio: number, phase: 'live' | 'commit') => {
      if (messages.length === 0) return
      const clamped = Math.max(0, Math.min(1, ratio))
      const idx =
        messages.length <= 1 ? 0 : Math.round(clamped * (messages.length - 1))
      const refineDom = phase === 'commit'
      scrollToMessageIndex(
        idx,
        {
          ordinal: messages[idx]?.ordinal_in_chat,
          messageId: (messages[idx]?.message_id ?? '').trim() || undefined,
        },
        refineDom,
      )
    },
    [messages, scrollToMessageIndex],
  )

  useEffect(() => {
    if (!chatId) return
    let cancelled = false

    setErr(null)
    setSearchHits([])
    setMessages([])
    setChat(null)

    async function load() {
      setLoading(true)
      try {
        const { messages: all, chat: c } = await fetchAllMessagesForChat(chatId!)
        if (cancelled) return
        setChat(c)
        setMessages(all)

        const hasMessageParam = isValidOrdinal || (messageIdParam != null && messageIdParam.trim() !== '')

        if (!hasMessageParam && all.length > 0) {
          setTimeout(() => {
            virtuosoRef.current?.scrollToIndex({
              index: all.length - 1,
              align: 'end',
              behavior: 'auto',
            })
          }, 50)
        }
      } catch (e) {
        if (!cancelled) setErr(String(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()

    return () => {
      cancelled = true
    }
  }, [chatId])

  useEffect(() => {
    if (!chatId || loading || messages.length === 0) return

    if (isValidOrdinal && chat && targetOrdinal! >= 1 && targetOrdinal! <= chat.message_count) {
      const idx = messages.findIndex((m) => m.ordinal_in_chat === targetOrdinal)
      if (idx >= 0) {
        const mid = (messages[idx].message_id ?? '').trim()
        setHighlightedMessageId(mid || null)
        scrollToMessageIndex(idx, { ordinal: targetOrdinal!, messageId: mid || undefined })
        const t1 = window.setTimeout(() => setHighlightedMessageId(null), 2200)
        return () => clearTimeout(t1)
      }
    }

    if (messageIdParam?.trim()) {
      const mid = messageIdParam.trim()
      const idx = messages.findIndex((m) => (m.message_id ?? '').trim() === mid)
      if (idx >= 0) {
        setHighlightedMessageId(mid)
        scrollToMessageIndex(idx, { messageId: mid, ordinal: messages[idx].ordinal_in_chat })
        const t1 = window.setTimeout(() => setHighlightedMessageId(null), 2200)
        return () => clearTimeout(t1)
      }
    }
  }, [chatId, chat, loading, messages, isValidOrdinal, targetOrdinal, messageIdParam, scrollToMessageIndex])

  function scrollToOrdinal(ordinal: number) {
    navigate(`/chat/${chatId}?message=${ordinal}`, { replace: true })
    const idx = messages.findIndex((m) => m.ordinal_in_chat === ordinal)
    if (idx >= 0) {
      const mid = (messages[idx].message_id ?? '').trim()
      setHighlightedMessageId(mid || null)
      scrollToMessageIndex(idx, { ordinal, messageId: mid || undefined })
      setTimeout(() => setHighlightedMessageId(null), 2200)
    }
  }

  const totalCount = chat?.message_count ?? messages.length

  const { currentRatio, currentTs } = useMemo(() => {
    if (messages.length === 0 || totalCount <= 1) return { currentRatio: 0, currentTs: null as string | null }
    const midIdx = Math.floor((visibleRange.startIndex + visibleRange.endIndex) / 2)
    const clampedIdx = Math.max(0, Math.min(midIdx, messages.length - 1))
    const midMsg = messages[clampedIdx]
    if (!midMsg) return { currentRatio: 0, currentTs: null as string | null }
    return {
      currentRatio: midMsg.ordinal_in_chat / Math.max(1, totalCount - 1),
      currentTs: midMsg.ts_utc ?? null,
    }
  }, [messages, visibleRange, totalCount])

  const senderOf = (m: Message | null | undefined): string | null => {
    if (!m) return null
    const s = (m.sender ?? '').toString().trim()
    return s || null
  }

  const distinctSenders = useMemo(() => {
    const set = new Set<string>()
    for (const m of messages) {
      const s = senderOf(m)
      if (s) set.add(s.toLowerCase())
    }
    return set
  }, [messages])

  const isGroupChat = distinctSenders.size >= 2
  const isMe = useCallback((m: Message) => !!m.is_sender, [])
  const hasHits = searchHits.length > 0
  const virtuosoKey = chatId ?? ''

  async function runChatSearch() {
    const needle = searchQ.trim()
    if (!needle || !chatId) return
    setErr(null)
    try {
      const r = await apiPost<any>('/api/search', { q: needle, chat_id: chatId, limit: 100, offset: 0 })
      const hits = (r.hits || []).slice()
      hits.sort((a: any, b: any) => (a.ordinal_in_chat ?? 0) - (b.ordinal_in_chat ?? 0))
      setSearchHits(hits)
    } catch (e) {
      setErr(String(e))
    }
  }

  function clearSearch() {
    setSearchQ('')
    setSearchHits([])
  }

  return (
    <div className="chatPage">
      <div className="chatHeader">
        <div className="chatHeaderLeft">
          <Link className="back" to="/">{t('chatPage.backToChats')}</Link>
          <h2 className="chatTitleH">{chat?.title || chatId}</h2>
          {chat ? (
            <span className="muted">{t('chatPage.meta', { textCount: chat.text_message_count, totalCount: chat.message_count })}</span>
          ) : null}
        </div>
        <div className="chatSearch">
          <input
            className="input"
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
            placeholder={t('chatPage.searchPlaceholder')}
            onKeyDown={(e) => { if (e.key === 'Enter') runChatSearch() }}
          />
          <button className="btn" onClick={runChatSearch}>{t('common.search')}</button>
          {hasHits && (
            <button className="btn btnGhost" onClick={clearSearch} title={t('chatPage.clearSearchTitle')}>✕</button>
          )}
        </div>
      </div>

      {err && <p className="err">{err}</p>}

      <div className={`chatBody ${hasHits ? 'withSearchPanel' : ''}`}>
        <div className="chatMainArea">
          <div className="chatListWithTimeline">
            <div className="chatListPane">
              {loading && (
                <div className="chatLoadingOverlay" aria-busy="true">
                  <span className="muted">{t('common.loading')}</span>
                </div>
              )}
              <Virtuoso
                key={virtuosoKey}
                ref={virtuosoRef}
                style={{ height: '100%' }}
                data={messages}
                followOutput={false}
                overscan={120}
                defaultItemHeight={72}
                rangeChanged={setVisibleRange}
                components={{
                  Scroller: CustomScroller,
                }}
                itemContent={(virtuosoIndex, m) => {
                  const dataIndex = virtuosoIndex
                  const mid = (m.message_id ?? '').trim()
                  const isFocused =
                    (highlightedMessageId !== null && mid === (highlightedMessageId ?? '').trim())
                  const mine = isMe(m)
                  const prev = dataIndex > 0 ? messages[dataIndex - 1] : null
                  const prevMine = prev ? isMe(prev) : null
                  const sideChanged = prevMine === null || prevMine !== mine
                  const mfn = m.media_filename
                  const isAudio = mfn && m.type === 'NOTE' && /\.(mp4|m4a|aac|ogg|mp3|wav|opus)$/i.test(mfn)
                  const isVideo = !isAudio && mfn ? /\.(mp4|mov|avi|mkv|webm)$/i.test(mfn) : false
                  return (
                    <div
                      className={`msgRow ${mine ? 'mine' : 'theirs'} ${sideChanged ? 'newBlock' : ''}`}
                      key={mid || virtuosoIndex}
                      data-message-id={mid || undefined}
                      data-ordinal={m.ordinal_in_chat}
                    >
                      <div className={`bubble ${isFocused ? 'focused' : ''}`}>
                        {isGroupChat && senderOf(m) && (
                          <span className="bubbleSender">{senderOf(m)}</span>
                        )}
                        {mfn && (
                          <div className="bubbleMedia">
                            {isAudio ? (
                              <audio src={mediaUrl(mfn)} className="bubbleAudio" controls preload="metadata" />
                            ) : isVideo ? (
                              <video src={mediaUrl(mfn)} className="bubbleMediaItem" controls preload="metadata" />
                            ) : (
                              <img src={mediaUrl(mfn)} className="bubbleMediaItem" alt="" loading="lazy" onClick={() => setLightboxSrc(mediaUrl(mfn))} />
                            )}
                          </div>
                        )}
                        {m.text ? (
                          <span className="bubbleText">{m.text}</span>
                        ) : !mfn ? (
                          <span className="bubbleText muted">
                            {!m.is_saved && m.type === 'TEXT' ? t('chatPage.notSaved')
                              : m.type === 'MEDIA' || m.type === 'VIDEO' ? t('chatPage.snapOrMedia')
                              : m.type === 'NOTE' ? t('chatPage.voiceOrVideoNote')
                              : m.type === 'STICKER' ? t('chatPage.sticker')
                              : m.type === 'SHARE' ? t('chatPage.sharedContent')
                              : m.type === 'LOCATION' ? t('chatPage.location')
                              : m.type === 'STATUS' || m.type === 'STATUSERASEDMESSAGE' ? t('chatPage.status')
                              : m.type === 'SHARESAVEDSTORY' ? t('chatPage.savedStory')
                              : '—'}
                          </span>
                        ) : null}
                        <span className="bubbleMeta">
                          {m.type !== 'TEXT' && <span className={`msgType type-${m.type.toLowerCase()}`}>{m.type}</span>}
                          {!!m.is_saved && <span className="msgSaved">{t('chatPage.saved')}</span>}
                          <span className="bubbleTime">{m.ts_utc?.slice(0, 16).replace('T', ' ') || '—'}</span>
                        </span>
                      </div>
                    </div>
                  )
                }}
              />
            </div>
            {chat ? (
              <TimelineScrollbar
                currentRatio={currentRatio}
                currentTs={currentTs}
                firstTs={chat.first_ts ?? undefined}
                lastTs={chat.last_ts ?? undefined}
                onSeekRatio={messages.length > 0 ? seekChatRatio : undefined}
              />
            ) : null}
          </div>
        </div>

        {hasHits && (
          <div className="searchPanel">
            <div className="searchPanelHeader">
              <strong>{t('chatPage.hits')}</strong>
              <span className="muted">{t('chatPage.hitsMeta', { count: searchHits.length })}</span>
            </div>
            <div className="searchPanelList">
              {searchHits.slice(0, 100).map((h) => (
                <button
                  key={h.message_id}
                  type="button"
                  className="hit"
                  onClick={() => scrollToOrdinal(h.ordinal_in_chat)}
                  title={t('chatPage.goToMessage', { ordinal: h.ordinal_in_chat })}
                >
                  <div className="hitTop">
                    <span className="hitSender">{h.sender ?? t('common.unknown')}</span>
                    <span className="hitMeta">#{h.ordinal_in_chat}</span>
                  </div>
                  <div
                    className="snippet"
                    dangerouslySetInnerHTML={{ __html: h._formatted?.text || h.text || '' }}
                  />
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {lightboxSrc && (
        <div className="lightboxOverlay" onClick={() => setLightboxSrc(null)}>
          <img src={lightboxSrc} className="lightboxImage" alt="" />
        </div>
      )}
    </div>
  )
}
