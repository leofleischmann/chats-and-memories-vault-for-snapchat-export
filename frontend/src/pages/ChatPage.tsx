import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { Virtuoso } from 'react-virtuoso'
import type { VirtuosoHandle } from 'react-virtuoso'
import { useTranslation } from 'react-i18next'
import { apiGet, apiPost, mediaUrl } from '../api'
import type { Chat, Message } from '../api'
import TimelineScrollbar from '../components/TimelineScrollbar'

function useQuery() {
  const { search } = useLocation()
  return useMemo(() => new URLSearchParams(search), [search])
}

const CustomScroller = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  (props, ref) => <div {...props} ref={ref} className="chatScrollerHideBar" />,
)
CustomScroller.displayName = 'CustomScroller'

const PAGE_SIZE = 500
const START_INDEX = 100_000

export default function ChatPage() {
  const { t } = useTranslation()
  const { chatId } = useParams()
  const query = useQuery()
  const focusMessageId = query.get('m')

  const [chat, setChat] = useState<Chat | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [allLoaded, setAllLoaded] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const [searchQ, setSearchQ] = useState('')
  const [searchHits, setSearchHits] = useState<any[]>([])
  const [visibleRange, setVisibleRange] = useState<{ startIndex: number; endIndex: number }>({ startIndex: 0, endIndex: 0 })
  const [highlightedMessageId, setHighlightedMessageId] = useState<string | null>(null)
  const highlightTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null)
  const [firstItemIndex, setFirstItemIndex] = useState(START_INDEX)
  const pagesLoadedRef = useRef(0)

  const virtuosoRef = useRef<VirtuosoHandle>(null)

  useEffect(() => {
    return () => {
      if (highlightTimeoutRef.current) clearTimeout(highlightTimeoutRef.current)
    }
  }, [])

  useEffect(() => {
    if (!chatId) return
    setLoading(true)
    setErr(null)
    setMessages([])
    setAllLoaded(false)
    setSearchHits([])
    setFirstItemIndex(START_INDEX)
    pagesLoadedRef.current = 0
    apiGet<{ messages: Message[]; chat: Chat }>(`/api/chats/${chatId}/messages?offset=0&limit=${PAGE_SIZE}`)
      .then((r) => {
        setChat(r.chat)
        setMessages(r.messages)
        pagesLoadedRef.current = 1
        if (r.messages.length < PAGE_SIZE || r.messages.length >= r.chat.message_count) {
          setAllLoaded(true)
        }
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false))
  }, [chatId])

  const [pendingScrollToOrdinal, setPendingScrollToOrdinal] = useState<number | null>(null)
  useEffect(() => {
    if (!focusMessageId || !chatId) return
    setPendingScrollToOrdinal(null)
    apiGet<any>(`/api/message/${encodeURIComponent(focusMessageId)}`)
      .then(async (m) => {
        const center = m.ordinal_in_chat as number
        const ctx = await apiGet<any>(
          `/api/chats/${chatId}/context?center_ordinal=${center}&before=200&after=200`,
        )
        setMessages(ctx.messages)
        setAllLoaded(true)
        setFirstItemIndex(START_INDEX)
        const idx = ctx.messages.findIndex((x: any) => x.message_id === focusMessageId)
        if (idx >= 0) setPendingScrollToOrdinal(center)
      })
      .catch(() => {})
  }, [focusMessageId, chatId])

  useEffect(() => {
    if (pendingScrollToOrdinal == null || !focusMessageId || messages.length === 0) return
    const idx = messages.findIndex((m) => m.message_id === focusMessageId)
    if (idx >= 0) {
      requestAnimationFrame(() => virtuosoRef.current?.scrollToIndex({ index: firstItemIndex + idx, align: 'center' }))
      setPendingScrollToOrdinal(null)
    }
  }, [messages, focusMessageId, pendingScrollToOrdinal, firstItemIndex])

  const loadOlderMessages = useCallback(() => {
    if (!chatId || !chat || loadingMore || allLoaded) return
    const nextOffset = pagesLoadedRef.current * PAGE_SIZE
    if (nextOffset >= chat.message_count) { setAllLoaded(true); return }
    setLoadingMore(true)
    apiGet<{ messages: Message[] }>(`/api/chats/${chatId}/messages?offset=${nextOffset}&limit=${PAGE_SIZE}`)
      .then((r) => {
        if (r.messages.length === 0) {
          setAllLoaded(true)
        } else {
          pagesLoadedRef.current += 1
          setFirstItemIndex((prev) => prev - r.messages.length)
          setMessages((prev) => [...r.messages, ...prev])
          if (r.messages.length < PAGE_SIZE) setAllLoaded(true)
        }
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoadingMore(false))
  }, [chatId, chat, loadingMore, allLoaded])

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

  const matchOrdinals = useMemo(() => {
    return searchHits.map((h) => h.ordinal_in_chat).filter((n) => typeof n === 'number')
  }, [searchHits])

  const totalCount = chat?.message_count ?? messages.length

  const jumpToOrdinal = useCallback(
    async (ordinal: number, messageIdToHighlight?: string) => {
      if (!chatId) return
      if (messageIdToHighlight) {
        if (highlightTimeoutRef.current) clearTimeout(highlightTimeoutRef.current)
        setHighlightedMessageId(messageIdToHighlight)
        highlightTimeoutRef.current = setTimeout(() => {
          setHighlightedMessageId(null)
          highlightTimeoutRef.current = null
        }, 2500)
      }
      const idx = messages.findIndex((m) => m.ordinal_in_chat === ordinal)
      if (idx >= 0) {
        virtuosoRef.current?.scrollToIndex({ index: firstItemIndex + idx, align: 'center' })
        return
      }
      const ctx = await apiGet<any>(
        `/api/chats/${chatId}/context?center_ordinal=${ordinal}&before=200&after=200`,
      )
      setMessages(ctx.messages)
      setAllLoaded(true)
      setFirstItemIndex(START_INDEX)
      const newIdx = ctx.messages.findIndex((m: Message) => m.ordinal_in_chat === ordinal)
      if (newIdx >= 0) {
        requestAnimationFrame(() => virtuosoRef.current?.scrollToIndex({ index: START_INDEX + newIdx, align: 'center' }))
      }
    },
    [chatId, messages, firstItemIndex],
  )

  const { currentRatio, currentTs } = useMemo(() => {
    if (messages.length === 0 || totalCount <= 1) return { currentRatio: 0, currentTs: null as string | null }
    const midIdx = Math.floor((visibleRange.startIndex - firstItemIndex + visibleRange.endIndex - firstItemIndex) / 2)
    const clampedIdx = Math.max(0, Math.min(midIdx, messages.length - 1))
    const midMsg = messages[clampedIdx]
    if (!midMsg) return { currentRatio: 0, currentTs: null as string | null }
    return {
      currentRatio: midMsg.ordinal_in_chat / Math.max(1, totalCount - 1),
      currentTs: midMsg.ts_utc ?? null,
    }
  }, [messages, visibleRange, totalCount, firstItemIndex])

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

  const isMe = useCallback(
    (m: Message) => {
      return !!m.is_sender
    },
    [],
  )

  const hasHits = searchHits.length > 0

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
      {loading ? <p className="muted">{t('common.loading')}</p> : null}

      <div className={`chatBody ${hasHits ? 'withSearchPanel' : ''}`}>
        <div className="chatMainArea">
          <div className="chatListWithTimeline">
            <div className="chatListPane">
              <Virtuoso
                ref={virtuosoRef}
                style={{ height: '100%' }}
                data={messages}
                firstItemIndex={firstItemIndex}
                initialTopMostItemIndex={messages.length > 0 ? messages.length - 1 : 0}
                startReached={loadOlderMessages}
                followOutput="smooth"
                overscan={200}
                rangeChanged={setVisibleRange}
                components={{
                  Scroller: CustomScroller,
                  Header: () =>
                    loadingMore ? (
                      <div style={{ padding: 12, textAlign: 'center', color: 'rgba(255,255,255,0.5)' }}>
                        {t('chatPage.loadingOlder')}
                      </div>
                    ) : null,
                }}
                itemContent={(_virtuosoIndex, m) => {
                  const dataIndex = _virtuosoIndex - firstItemIndex
                  const isFocused =
                    (focusMessageId && m.message_id === focusMessageId) ||
                    (highlightedMessageId !== null && m.message_id === highlightedMessageId)
                  const mine = isMe(m)
                  const prev = dataIndex > 0 ? messages[dataIndex - 1] : null
                  const prevMine = prev ? isMe(prev) : null
                  const sideChanged = prevMine === null || prevMine !== mine
                  const mfn = m.media_filename
                  const isAudio = mfn && m.type === 'NOTE' && /\.(mp4|m4a|aac|ogg|mp3|wav|opus)$/i.test(mfn)
                  const isVideo = !isAudio && mfn ? /\.(mp4|mov|avi|mkv|webm)$/i.test(mfn) : false
                  return (
                    <div className={`msgRow ${mine ? 'mine' : 'theirs'} ${sideChanged ? 'newBlock' : ''}`}>
                      <div className={`bubble ${isFocused ? 'focused' : ''}`}>
                        {isGroupChat && senderOf(m) && (
                          <span className="bubbleSender">{senderOf(m)}</span>
                        )}
                        {mfn && (
                          <div className="bubbleMedia">
                            {isAudio ? (
                              <audio
                                src={mediaUrl(mfn)}
                                className="bubbleAudio"
                                controls
                                preload="metadata"
                              />
                            ) : isVideo ? (
                              <video
                                src={mediaUrl(mfn)}
                                className="bubbleMediaItem"
                                controls
                                preload="metadata"
                              />
                            ) : (
                              <img
                                src={mediaUrl(mfn)}
                                className="bubbleMediaItem"
                                alt=""
                                loading="lazy"
                                onClick={() => setLightboxSrc(mediaUrl(mfn))}
                              />
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
                totalCount={totalCount}
                currentRatio={currentRatio}
                currentTs={currentTs}
                hitOrdinals={matchOrdinals}
                onJumpToOrdinal={jumpToOrdinal}
                firstTs={chat.first_ts ?? undefined}
                lastTs={chat.last_ts ?? undefined}
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
                  className="hit"
                  onClick={() => jumpToOrdinal(h.ordinal_in_chat, h.message_id)}
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
