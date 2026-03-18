import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiGet, apiPost } from '../api'
import type { Chat } from '../api'

export default function ChatsPage() {
  const { t } = useTranslation()
  const [chats, setChats] = useState<Chat[]>([])
  const [q, setQ] = useState('')
  const [searchQ, setSearchQ] = useState('')
  const [results, setResults] = useState<any | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    apiGet<{ chats: Chat[] }>('/api/chats')
      .then((r) => setChats(r.chats))
      .catch((e) => setErr(String(e)))
  }, [])

  const filteredChats = useMemo(() => {
    const needle = q.trim().toLowerCase()
    if (!needle) return chats
    return chats.filter((c) => c.title.toLowerCase().includes(needle))
  }, [chats, q])

  async function runGlobalSearch() {
    const needle = searchQ.trim()
    if (!needle) return
    setLoading(true)
    setErr(null)
    try {
      const r = await apiPost<any>('/api/search', { q: needle, limit: 25, offset: 0 })
      setResults(r)
    } catch (e) {
      setErr(String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page">
      <section className="panel">
        <h2>{t('chatsPage.globalSearch')}</h2>
        <div className="row">
          <input
            className="input"
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
            placeholder={t('chatsPage.globalSearchPlaceholder')}
            onKeyDown={(e) => {
              if (e.key === 'Enter') runGlobalSearch()
            }}
          />
          <button className="btn" onClick={runGlobalSearch} disabled={loading}>
            {t('common.search')}
          </button>
        </div>
        {err && <p className="err">{err}</p>}
        {results?.hits?.length ? (
          <div className="results">
            {results.hits.map((h: any) => (
              <Link
                key={h.message_id}
                className="resultItem"
                to={`/chat/${h.chat_id}?m=${encodeURIComponent(h.message_id)}`}
              >
                <div className="resultTop">
                  <span className="resultChat">{h.chat_title}</span>
                  <span className="resultMeta">
                    {h.sender || '—'} · {h.ts_utc || '—'}
                  </span>
                </div>
                <div
                  className="snippet"
                  dangerouslySetInnerHTML={{
                    __html:
                      h._formatted?.text ||
                      h.text ||
                      '',
                  }}
                />
              </Link>
            ))}
          </div>
        ) : results ? (
          <p className="muted">{t('chatsPage.noHits')}</p>
        ) : null}
      </section>

      <section className="panel">
        <div className="panelHeader">
          <h2>{t('chatsPage.chats')}</h2>
          <span className="muted">{filteredChats.length} / {chats.length}</span>
        </div>
        <input
          className="input"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t('chatsPage.filterPlaceholder')}
        />
        <div className="chatList">
          {filteredChats.map((c) => (
            <Link key={c.chat_id} className="chatRow" to={`/chat/${c.chat_id}`}>
              <div className="chatTitle">{c.title}</div>
              <div className="chatMeta">
                <span className="pill">{c.text_message_count} {t('chatsPage.text')}</span>
                <span className="pill">{c.message_count} {t('chatsPage.total')}</span>
              </div>
            </Link>
          ))}
        </div>
      </section>
    </div>
  )
}

