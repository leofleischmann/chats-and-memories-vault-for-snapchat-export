import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useTranslation } from 'react-i18next'
import { apiGet } from '../api'
import type { Chat } from '../api'
import { formatDateTime, formatNumber, uiLocale } from '../i18nFormat'

type SnapThread = { thread_id: string; thread_title: string; snap_count?: number }

function weekdayLabels(lang: string): string[] {
  return uiLocale(lang).startsWith('de')
    ? ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa']
    : ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
}

type Stats = {
  messages_over_time: { period: string; count: number }[]
  chat_media_over_time: { period: string; count: number }[]
  snaps_over_time: { period: string; count: number }[]
  by_type: { type: string; count: number }[]
  by_sender: { sender: string; count: number }[]
  total_messages: number
  total_chat_media: number
  total_snaps: number
  by_hour?: { hour: number; count: number }[]
  by_weekday?: { weekday: number; count: number }[]
  top_days?: { day: string; count: number }[]
  avg_message_length?: number | null
}

type Insights = {
  meta: Record<string, string>
  engagement: { event: string; occurrences: number }[]
  time_spent: { area: string; percent: number }[]
  interests: { category: string; kind: 'interest' | 'content' }[]
  web_interactions: string[]
  ranking: Record<string, string>
  device_history: { start_ts?: string | null; make?: string | null; model?: string | null; device_type?: string | null }[]
  login_history: {
    created_ts?: string | null
    ip?: string | null
    country?: string | null
    status?: string | null
    device?: string | null
  }[]
  account_history: { section: string; created_ts?: string | null; value: string }[]
}

const COLORS = ['#ff6b6b', '#4ecdc4', '#45b7d1', '#96ceb4', '#ffeaa7', '#dfe6e9', '#fd79a8']

/** Validiert YYYY-MM-DD und liefert ein gültiges Datum; ungültige Tage werden auf den letzten Tag des Monats gesetzt. */
function normalizeDate(dateStr: string): string | null {
  if (!dateStr || !/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) return null
  const [y, m, d] = dateStr.split('-').map(Number)
  const date = new Date(Date.UTC(y, m - 1, d))
  if (date.getUTCFullYear() !== y || date.getUTCMonth() !== m - 1) {
    const lastDay = new Date(Date.UTC(y, m, 0)).getUTCDate()
    return `${y}-${String(m).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`
  }
  return dateStr
}

export default function StatsPage() {
  const { t, i18n } = useTranslation()
  const [chats, setChats] = useState<Chat[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [insights, setInsights] = useState<Insights | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  const [filterChatId, setFilterChatId] = useState<string>('')
  const [filterThreadId, setFilterThreadId] = useState<string>('')
  const [filterFrom, setFilterFrom] = useState('')
  const [filterTo, setFilterTo] = useState('')
  const [groupBy, setGroupBy] = useState<'day' | 'month'>('month')
  const [snapThreads, setSnapThreads] = useState<SnapThread[]>([])

  const filterChatIdRef = useRef(filterChatId)
  const filterThreadIdRef = useRef(filterThreadId)
  const filterFromRef = useRef(filterFrom)
  const filterToRef = useRef(filterTo)
  const groupByRef = useRef(groupBy)
  filterChatIdRef.current = filterChatId
  filterThreadIdRef.current = filterThreadId
  filterFromRef.current = filterFrom
  filterToRef.current = filterTo
  groupByRef.current = groupBy

  const loadStats = useCallback(() => {
    setLoading(true)
    setErr(null)
    const params = new URLSearchParams()
    if (filterChatIdRef.current) params.set('chat_id', filterChatIdRef.current)
    if (filterThreadIdRef.current) params.set('thread_id', filterThreadIdRef.current)
    const fromNorm = normalizeDate(filterFromRef.current)
    if (fromNorm) params.set('from_ts', fromNorm + 'T00:00:00Z')
    const toNorm = normalizeDate(filterToRef.current)
    if (toNorm) params.set('to_ts', toNorm + 'T23:59:59Z')
    params.set('group_by', groupByRef.current)
    apiGet<Stats>(`/api/stats?${params}`)
      .then(setStats)
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    apiGet<{ chats: Chat[] }>('/api/chats')
      .then((r) => setChats(r.chats || []))
      .catch((e) => setErr(String(e)))
    apiGet<{ threads: SnapThread[] }>('/api/snap_threads')
      .then((r) => setSnapThreads(r.threads || []))
      .catch(() => setSnapThreads([]))
    apiGet<Insights>('/api/insights')
      .then(setInsights)
      .catch(() => setInsights(null))
    loadStats()
  }, [loadStats])

  const chartHeight = 280

  // Alle 24 Stunden befüllt (API liefert nur vorhandene)
  const byHourData = (() => {
    const map = new Map((stats?.by_hour ?? []).map((h) => [h.hour, h.count]))
    return Array.from({ length: 24 }, (_, i) => ({ hour: i, count: map.get(i) ?? 0, label: `${i}:00` }))
  })()

  // Wochentage 0–6 mit Labels
  const byWeekdayData = (() => {
    const map = new Map((stats?.by_weekday ?? []).map((w) => [w.weekday, w.count]))
    const labels = weekdayLabels(i18n.language)
    return Array.from({ length: 7 }, (_, i) => ({
      weekday: i,
      label: labels[i],
      count: map.get(i) ?? 0,
    }))
  })()

  return (
    <div className="statsPage">
      <h1 className="pageTitle">{t('stats.title')}</h1>

      <div className="statsFilters panel">
        <h3>{t('stats.filters')}</h3>
        <div className="filterRow">
          <label>
            {t('stats.chat')}
            <select
              className="input"
              value={filterChatId}
              onChange={(e) => setFilterChatId(e.target.value)}
              style={{ minWidth: 200 }}
            >
              <option value="">{t('common.all')} {t('nav.chats')}</option>
              {chats.map((c) => (
                <option key={c.chat_id} value={c.chat_id}>
                  {c.title} ({c.message_count})
                </option>
              ))}
            </select>
          </label>
          <label>
            {t('stats.snapPartner')}
            <select
              className="input"
              value={filterThreadId}
              onChange={(e) => setFilterThreadId(e.target.value)}
              style={{ minWidth: 180 }}
            >
              <option value="">{t('common.all')} ({formatNumber(i18n.language, stats?.total_snaps ?? 0)} {t('chatsPage.total')})</option>
              {snapThreads.map((t0) => (
                <option key={t0.thread_id} value={t0.thread_id}>
                  {(t0.thread_title?.trim() || t0.thread_id || t('common.unknown'))} ({formatNumber(i18n.language, t0.snap_count ?? 0)} Snaps)
                </option>
              ))}
            </select>
          </label>
          <label>
            {t('stats.fromDate')}
            <input
              type="date"
              className="input"
              value={filterFrom}
              onChange={(e) => setFilterFrom(e.target.value)}
            />
          </label>
          <label>
            {t('stats.toDate')}
            <input
              type="date"
              className="input"
              value={filterTo}
              onChange={(e) => setFilterTo(e.target.value)}
            />
          </label>
          <label>
            {t('stats.grouping')}
            <select
              className="input"
              value={groupBy}
              onChange={(e) => setGroupBy(e.target.value as 'day' | 'month')}
            >
              <option value="day">{t('stats.day')}</option>
              <option value="month">{t('stats.month')}</option>
            </select>
          </label>
          <button type="button" className="btn" onClick={loadStats}>
            {t('stats.refresh')}
          </button>
        </div>
      </div>

      {err && <p className="err">{err}</p>}
      {loading && <p className="muted">{t('stats.loading')}</p>}

      {!loading && stats && (
        <>
          <div className="statsSummary">
            <div className="statCard">
              <span className="statValue">{formatNumber(i18n.language, stats.total_messages)}</span>
              <span className="statLabel">{t('stats.summary.messages')}</span>
            </div>
            <div className="statCard">
              <span className="statValue">{formatNumber(i18n.language, stats.total_chat_media ?? 0)}</span>
              <span className="statLabel">{t('stats.summary.chatMedia')}</span>
            </div>
            <div className="statCard">
              <span className="statValue">{formatNumber(i18n.language, stats.total_snaps ?? 0)}</span>
              <span className="statLabel">{t('stats.summary.snaps')}</span>
            </div>
            {stats.avg_message_length != null && (
              <div className="statCard">
                <span className="statValue">{stats.avg_message_length.toFixed(1)}</span>
                <span className="statLabel">{t('stats.summary.avgLen')}</span>
              </div>
            )}
          </div>

          <div className="statsCharts">
            <div className="panel chartPanel">
              <h3>{t('stats.charts.messagesOverTime')}</h3>
              <ResponsiveContainer width="100%" height={chartHeight}>
                <LineChart data={stats.messages_over_time} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                  <XAxis dataKey="period" stroke="rgba(255,255,255,0.6)" fontSize={12} />
                  <YAxis stroke="rgba(255,255,255,0.6)" fontSize={12} />
                  <Tooltip
                    contentStyle={{ background: '#1a1a1a', border: '1px solid rgba(255,255,255,0.2)' }}
                    labelStyle={{ color: '#fff' }}
                  />
                  <Line type="monotone" dataKey="count" name={t('stats.summary.messages')} stroke="#4ecdc4" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="panel chartPanel">
              <h3>{t('stats.charts.chatMediaOverTime')}</h3>
              <ResponsiveContainer width="100%" height={chartHeight}>
                <LineChart data={stats.chat_media_over_time ?? []} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                  <XAxis dataKey="period" stroke="rgba(255,255,255,0.6)" fontSize={12} />
                  <YAxis stroke="rgba(255,255,255,0.6)" fontSize={12} />
                  <Tooltip
                    contentStyle={{ background: '#1a1a1a', border: '1px solid rgba(255,255,255,0.2)' }}
                    labelStyle={{ color: '#fff' }}
                  />
                  <Line type="monotone" dataKey="count" name={t('stats.summary.chatMedia')} stroke="#96ceb4" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="panel chartPanel">
              <h3>{t('stats.charts.snapsOverTime')}</h3>
              <ResponsiveContainer width="100%" height={chartHeight}>
                <LineChart data={stats.snaps_over_time ?? []} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                  <XAxis dataKey="period" stroke="rgba(255,255,255,0.6)" fontSize={12} />
                  <YAxis stroke="rgba(255,255,255,0.6)" fontSize={12} />
                  <Tooltip
                    contentStyle={{ background: '#1a1a1a', border: '1px solid rgba(255,255,255,0.2)' }}
                    labelStyle={{ color: '#fff' }}
                  />
                  <Line type="monotone" dataKey="count" name="Snaps" stroke="#fd79a8" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="panel chartPanel">
              <h3>{t('stats.charts.byType')}</h3>
              <ResponsiveContainer width="100%" height={chartHeight}>
                <BarChart data={stats.by_type} layout="vertical" margin={{ top: 8, right: 16, left: 60, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                  <XAxis type="number" stroke="rgba(255,255,255,0.6)" fontSize={12} />
                  <YAxis type="category" dataKey="type" stroke="rgba(255,255,255,0.6)" fontSize={12} width={50} />
                  <Tooltip
                    contentStyle={{ background: '#1a1a1a', border: '1px solid rgba(255,255,255,0.2)' }}
                  />
                  <Bar dataKey="count" name={t('stats.snapExportInsights.occurrences')} fill="#45b7d1" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="panel chartPanel">
              <h3>{t('stats.charts.typeDistribution')}</h3>
              <ResponsiveContainer width="100%" height={chartHeight}>
                <PieChart>
                  <Pie
                    data={stats.by_type}
                    dataKey="count"
                    nameKey="type"
                    cx="50%"
                    cy="50%"
                    outerRadius={90}
                    label={(p: any) => `${p?.payload?.type ?? ''}: ${p?.payload?.count ?? ''}`}
                  >
                    {stats.by_type.map((_, i) => (
                      <Cell key={i} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ background: '#1a1a1a', border: '1px solid rgba(255,255,255,0.2)' }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>

            <div className="panel chartPanel">
              <h3>{t('stats.charts.activityByHour')}</h3>
              <ResponsiveContainer width="100%" height={chartHeight}>
                <BarChart data={byHourData} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                  <XAxis dataKey="label" stroke="rgba(255,255,255,0.6)" fontSize={10} interval={1} />
                  <YAxis stroke="rgba(255,255,255,0.6)" fontSize={12} />
                  <Tooltip
                    contentStyle={{ background: '#1a1a1a', border: '1px solid rgba(255,255,255,0.2)' }}
                    labelFormatter={(_, payload) => payload?.[0]?.payload ? t('stats.charts.hourLabel', { hour: payload[0].payload.hour }) : ''}
                  />
                  <Bar dataKey="count" name={t('stats.summary.messages')} fill="#4ecdc4" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="panel chartPanel">
              <h3>{t('stats.charts.activityByWeekday')}</h3>
              <ResponsiveContainer width="100%" height={chartHeight}>
                <BarChart data={byWeekdayData} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                  <XAxis dataKey="label" stroke="rgba(255,255,255,0.6)" fontSize={12} />
                  <YAxis stroke="rgba(255,255,255,0.6)" fontSize={12} />
                  <Tooltip
                    contentStyle={{ background: '#1a1a1a', border: '1px solid rgba(255,255,255,0.2)' }}
                  />
                  <Bar dataKey="count" name={t('stats.summary.messages')} fill="#96ceb4" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="panel chartPanel">
              <h3>{t('stats.charts.topDays')}</h3>
              <ResponsiveContainer width="100%" height={chartHeight}>
                <BarChart
                  data={stats.top_days ?? []}
                  layout="vertical"
                  margin={{ top: 8, right: 16, left: 48, bottom: 8 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                  <XAxis type="number" stroke="rgba(255,255,255,0.6)" fontSize={12} />
                  <YAxis type="category" dataKey="day" stroke="rgba(255,255,255,0.6)" fontSize={11} width={48} />
                  <Tooltip
                    contentStyle={{ background: '#1a1a1a', border: '1px solid rgba(255,255,255,0.2)' }}
                  />
                  <Bar dataKey="count" name={t('stats.summary.messages')} fill="#ffeaa7" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="panel chartPanel">
            <div className="insightsSectionHeader">
              <h2>{t('stats.snapExportInsights.title')}</h2>
              <p className="muted">{t('stats.snapExportInsights.subtitle')}</p>
            </div>

            {!insights && <p className="muted">{t('stats.snapExportInsights.noneFound')}</p>}

            {insights && (
              <>
                <div className="insightsGrid">
                  <div className="panel insightsCard">
                    <div className="insightsCardHeader">
                      <h3>{t('stats.snapExportInsights.ranking')}</h3>
                      <span className="muted">{t('stats.snapExportInsights.rankingHint')}</span>
                    </div>
                    {Object.keys(insights.ranking || {}).length === 0 ? (
                      <p className="muted">{t('stats.snapExportInsights.noRanking')}</p>
                    ) : (
                      <div className="kvList">
                        {Object.entries(insights.ranking).map(([k, v]) => (
                          <div className="kvRow" key={k}>
                            <span className="kvKey">{k}</span>
                            <span className="kvVal">{v}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="panel insightsCard">
                    <div className="insightsCardHeader">
                      <h3>{t('stats.snapExportInsights.engagement')}</h3>
                      <span className="muted">Top 12</span>
                    </div>
                    {insights.engagement?.length ? (
                      <ResponsiveContainer width="100%" height={260}>
                        <BarChart data={insights.engagement.slice(0, 12)} layout="vertical" margin={{ top: 8, right: 16, left: 80, bottom: 8 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                          <XAxis type="number" stroke="rgba(255,255,255,0.6)" fontSize={12} />
                          <YAxis type="category" dataKey="event" stroke="rgba(255,255,255,0.6)" fontSize={11} width={80} />
                          <Tooltip contentStyle={{ background: '#1a1a1a', border: '1px solid rgba(255,255,255,0.2)' }} />
                          <Bar dataKey="occurrences" name={t('stats.snapExportInsights.occurrences')} fill="#4ecdc4" radius={[0, 4, 4, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    ) : (
                      <p className="muted">{t('stats.snapExportInsights.noEngagement')}</p>
                    )}
                  </div>

                  <div className="panel insightsCard">
                    <div className="insightsCardHeader">
                      <h3>{t('stats.snapExportInsights.timeSpent')}</h3>
                      <span className="muted">{t('stats.snapExportInsights.appAreas')}</span>
                    </div>
                    {insights.time_spent?.length ? (
                      <ResponsiveContainer width="100%" height={260}>
                        <PieChart>
                          <Pie
                            data={insights.time_spent}
                            dataKey="percent"
                            nameKey="area"
                            cx="50%"
                            cy="50%"
                            outerRadius={90}
                            label={(p: any) => {
                              const area = p?.payload?.area ?? ''
                              const percent = p?.payload?.percent
                              return `${area}: ${Number(percent ?? 0).toFixed(1)}%`
                            }}
                          >
                            {insights.time_spent.map((_, i) => (
                              <Cell key={i} fill={COLORS[i % COLORS.length]} />
                            ))}
                          </Pie>
                          <Tooltip contentStyle={{ background: '#1a1a1a', border: '1px solid rgba(255,255,255,0.2)' }} />
                        </PieChart>
                      </ResponsiveContainer>
                    ) : (
                      <p className="muted">{t('stats.snapExportInsights.noTimeSpent')}</p>
                    )}
                  </div>

                </div>

                <div className="insightsDisclosures">
                  <details className="panel insightsDisclosure">
                    <summary>
                      <span>{t('stats.snapExportInsights.webInteractions')}</span>
                      <span className="muted">{formatNumber(i18n.language, insights.web_interactions?.length ?? 0)}</span>
                    </summary>
                    <p className="muted">
                      {t('stats.snapExportInsights.webInteractionsHint')}
                    </p>
                    <div className="scrollBox">
                      <ul className="senderList">
                        {(insights.web_interactions ?? []).map((d) => (
                          <li key={d}>
                            <span className="senderName">{d}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </details>

                  <details className="panel insightsDisclosure">
                    <summary>
                      <span>{t('stats.snapExportInsights.accountDeviceLogin')}</span>
                    </summary>
                    <p className="muted">
                      {t('stats.snapExportInsights.accountDeviceLoginHint')}
                    </p>

                    <div className="insightsSubGrid">
                      <div className="panel insightsSubCard">
                        <div className="insightsCardHeader">
                          <h3>{t('stats.snapExportInsights.deviceHistory')}</h3>
                          <span className="muted">{t('stats.snapExportInsights.lastN', { n: 50 })}</span>
                        </div>
                        <div className="scrollBox">
                          <ul className="senderList">
                            {(insights.device_history ?? []).slice(0, 50).map((d, idx) => (
                              <li key={`${d.start_ts ?? 'x'}:${idx}`} style={{ justifyContent: 'space-between' }}>
                                <span className="senderName">{[d.make, d.model, d.device_type].filter(Boolean).join(' · ') || t('common.unknown')}</span>
                                <span className="senderCount">{formatDateTime(i18n.language, d.start_ts)}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      </div>

                      <div className="panel insightsSubCard">
                        <div className="insightsCardHeader">
                          <h3>{t('stats.snapExportInsights.loginHistory')}</h3>
                          <span className="muted">{t('stats.snapExportInsights.lastN', { n: 50 })}</span>
                        </div>
                        <div className="scrollBox">
                          <ul className="senderList">
                            {(insights.login_history ?? []).slice(0, 50).map((l, idx) => (
                              <li key={`${l.created_ts ?? 'x'}:${idx}`} style={{ justifyContent: 'space-between' }}>
                                <span className="senderName">{[l.status, l.country, l.ip].filter(Boolean).join(' · ') || t('common.unknown')}</span>
                                <span className="senderCount">{formatDateTime(i18n.language, l.created_ts)}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      </div>

                      <div className="panel insightsSubCard insightsSubCardWide">
                        <div className="insightsCardHeader">
                          <h3>{t('stats.snapExportInsights.accountHistory')}</h3>
                          <span className="muted">{t('stats.snapExportInsights.lastN', { n: 80 })}</span>
                        </div>
                        <div className="scrollBox">
                          <ul className="senderList">
                            {(insights.account_history ?? []).slice(0, 80).map((a, idx) => (
                              <li key={`${a.section}:${a.created_ts ?? 'x'}:${idx}`} style={{ justifyContent: 'space-between' }}>
                                <span className="senderName">{a.section}: {a.value}</span>
                                <span className="senderCount">{formatDateTime(i18n.language, a.created_ts)}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      </div>
                    </div>
                  </details>
                </div>
              </>
            )}
          </div>

          <div className="statsLongLists">
            <div className="panel chartPanel statsLongListCard">
              <h3>{t('stats.charts.topSenders')}</h3>
              <div className="scrollBox">
                <ul className="senderList">
                  {stats.by_sender.map((s, i) => (
                    <li key={s.sender}>
                      <span className="senderRank">{i + 1}.</span>
                      <span className="senderName">{s.sender}</span>
                      <span className="senderCount">{formatNumber(i18n.language, s.count)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
            {insights && (
              <div className="panel chartPanel statsLongListCard">
                <h3>{t('stats.snapExportInsights.categories')}</h3>
                <span className="muted" style={{ display: 'block', marginBottom: 8 }}>{t('stats.snapExportInsights.interestsAndContent')}</span>
                {insights.interests?.length ? (
                  <div className="scrollBox">
                    <div className="insightsTwoCol">
                      <div>
                        <div className="pillHeader">Interest ({insights.interests.filter((i) => i.kind === 'interest').length})</div>
                        <ul className="tagList">
                          {insights.interests
                            .filter((i) => i.kind === 'interest')
                            .slice(0, 60)
                            .map((i) => (
                              <li className="tag" key={`interest:${i.category}`}>{i.category}</li>
                            ))}
                        </ul>
                      </div>
                      <div>
                        <div className="pillHeader">Content ({insights.interests.filter((i) => i.kind === 'content').length})</div>
                        <ul className="tagList">
                          {insights.interests
                            .filter((i) => i.kind === 'content')
                            .slice(0, 60)
                            .map((i) => (
                              <li className="tag" key={`content:${i.category}`}>{i.category}</li>
                            ))}
                        </ul>
                      </div>
                    </div>
                  </div>
                ) : (
                  <p className="muted">{t('stats.snapExportInsights.noCategories')}</p>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
