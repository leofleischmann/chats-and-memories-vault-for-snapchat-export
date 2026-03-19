import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
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

const PAGE_SIZE = 500
const START_INDEX = 100_000

export default function ChatPage() {
  const { t } = useTranslation()
  const { chatId } = useParams()

  const [chat, setChat] = useState<Chat | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [allLoaded, setAllLoaded] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const [searchQ, setSearchQ] = useState('')
  const [searchHits, setSearchHits] = useState<any[]>([])
  const [visibleRange, setVisibleRange] = useState<{ startIndex: number; endIndex: number }>({ startIndex: 0, endIndex: 0 })
  
  const [highlightedMessageId] = useState<string | null>(null)
  
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null)
  const [firstItemIndex, setFirstItemIndex] = useState(START_INDEX)
  const pagesLoadedRef = useRef(0)

  const virtuosoRef = useRef<VirtuosoHandle>(null)

  useEffect(() => {
    if (!chatId) return
    let cancelled = false

    setErr(null)
    setSearchHits([])
    setMessages([])
    setAllLoaded(false)
    setFirstItemIndex(START_INDEX)
    pagesLoadedRef.current = 0

    async function loadDefaultList() {
      setLoading(true)
      try {
        const r = await apiGet<{ messages: Message[]; chat: Chat }>(
          `/api/chats/${encodeURIComponent(chatId!)}/messages?offset=0&limit=${PAGE_SIZE}`,
        )
        if (cancelled) return
        
        setChat(r.chat)
        setMessages(r.messages)
        setFirstItemIndex(START_INDEX)
        pagesLoadedRef.current = 1
        
        if (r.messages.length < PAGE_SIZE || r.messages.length >= r.chat.message_count) {
          setAllLoaded(true)
        }

        // Automatisch nach ganz unten scrollen bei regulärem Ladevorgang
        if (r.messages.length > 0) {
          setTimeout(() => {
            virtuosoRef.current?.scrollToIndex({ index: START_INDEX + r.messages.length - 1, align: 'end' })
          }, 100)
        }
      } catch (e) {
        if (!cancelled) setErr(String(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    loadDefaultList()

    return () => {
      cancelled = true
    }
  }, [chatId])

  const loadOlderMessages = useCallback(() => {
    if (!chatId || !chat || loadingMore || allLoaded) return
    const nextOffset = pagesLoadedRef.current * PAGE_SIZE
    if (nextOffset >= chat.message_count) { setAllLoaded(true); return }
    setLoadingMore(true)
    apiGet<{ messages: Message[] }>(
      `/api/chats/${encodeURIComponent(chatId)}/messages?offset=${nextOffset}&limit=${PAGE_SIZE}`,
    )
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

  const totalCount = chat?.message_count ?? messages.length

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
  const isMe = useCallback((m: Message) => !!m.is_sender, [])
  const hasHits = searchHits.length > 0
  const virtuosoKey = chatId ?? ''

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
                firstItemIndex={firstItemIndex}
                startReached={loadOlderMessages}
                followOutput={false}
                overscan={80}
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
                      key={mid || _virtuosoIndex}
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
                <div
                  key={h.message_id}
                  className="hit"
                >
                  <div className="hitTop">
                    <span className="hitSender">{h.sender ?? t('common.unknown')}</span>
                    <span className="hitMeta">#{h.ordinal_in_chat}</span>
                  </div>
                  <div
                    className="snippet"
                    dangerouslySetInnerHTML={{ __html: h._formatted?.text || h.text || '' }}
                  />
                </div>
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