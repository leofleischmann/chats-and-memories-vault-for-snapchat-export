import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { formatDateShort, formatNumber } from '../i18nFormat'

interface DashboardStats {
  chat_count: number
  message_count: number
  media_message_count: number
  media_file_count: number
  assigned_media: number
  unassigned_media: number
  snap_count: number
  memory_count: number
  first_message: string | null
  last_message: string | null
}

interface ImmichStatus {
  configured: boolean
  reachable: boolean
  key_valid: boolean
}

type AdminResp = {
  ok: boolean
  message: string
  details?: any
}

type UnpackImportProgress = {
  phase: string
  current: number
  total: number
  message: string
  error?: string | null
  result?: any
}

export default function DashboardPage() {
  const { t, i18n } = useTranslation()
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [immich, setImmich] = useState<ImmichStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [adminMsg, setAdminMsg] = useState<string | null>(null)
  const [job, setJob] = useState<UnpackImportProgress | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const busyLabel: Record<string, string> = {
    '/api/admin/unpack': t('dashboard.busy.unpack'),
    '/api/import': t('dashboard.busy.import'),
    '/api/admin/unpack-import': t('dashboard.busy.unpackImport'),
    '/api/admin/reset-app': t('dashboard.busy.resetApp'),
    '/api/admin/reset-immich': t('dashboard.busy.resetImmich'),
  }

  useEffect(() => {
    reload()
  }, [])

  useEffect(() => {
    // Resume progress polling after page reload
    fetch('/api/admin/unpack-import-progress')
      .then(r => r.ok ? r.json() : null)
      .then((p: UnpackImportProgress | null) => {
        if (!p) return
        setJob(p)
        const running = ['starting', 'unpack', 'import'].includes(p.phase)
        if (running) startPolling()
      })
      .catch(() => {})
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [])

  function reload() {
    setLoading(true)
    return Promise.all([
      fetch('/api/dashboard').then(r => r.ok ? r.json() : null),
      fetch('/api/immich/status').then(r => r.ok ? r.json() : null).catch(() => null),
    ]).then(([d, i]) => {
      setStats(d)
      setImmich(i)
      setLoading(false)
    }).catch(() => setLoading(false))
  }

  function startPolling() {
    if (pollRef.current) return
    const poll = () => {
      fetch('/api/admin/unpack-import-progress')
        .then(r => r.ok ? r.json() : null)
        .then((p: UnpackImportProgress | null) => {
          if (!p) return
          setJob(p)
          if (p.phase === 'done') {
            setBusy(null)
            if (pollRef.current) {
              clearInterval(pollRef.current)
              pollRef.current = null
            }
            reload()
          } else if (p.phase === 'error') {
            setBusy(null)
            setAdminMsg(`${t('dashboard.admin.errorPrefix')}${p.error || t('dashboard.admin.unknownError')}`)
            if (pollRef.current) {
              clearInterval(pollRef.current)
              pollRef.current = null
            }
          }
        })
        .catch(() => {})
    }
    poll()
    pollRef.current = setInterval(poll, 1000)
  }

  async function runAdmin(path: string, body?: any, confirmText?: string) {
    setAdminMsg(null)
    if (confirmText && !confirm(confirmText)) return
    setBusy(path)
    try {
      const r = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
      })
      const data = (await r.json().catch(() => null)) as AdminResp | null
      if (!r.ok) {
        setAdminMsg(`${t('dashboard.admin.errorPrefix')}${data?.message || (data as any)?.detail || `HTTP ${r.status}`}`)
      } else {
        setAdminMsg(data?.message || t('common.ok'))
        await reload()
      }
    } catch (e: any) {
      setAdminMsg(`${t('dashboard.admin.errorPrefix')}${e?.message || String(e)}`)
    } finally {
      setBusy(null)
    }
  }

  async function runUnpackAndImport() {
    setAdminMsg(null)
    const ok = confirm(t('dashboard.confirm.unpackAndImport'))
    if (!ok) return

    try {
      setBusy('/api/admin/reset-app')
      const resetR = await fetch('/api/admin/reset-app', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      const resetData = (await resetR.json().catch(() => null)) as AdminResp | null
      if (!resetR.ok) {
        setAdminMsg(`${t('dashboard.admin.errorPrefix')}${resetData?.message || (resetData as any)?.detail || `HTTP ${resetR.status}`}`)
        setBusy(null)
        return
      }

      setBusy('/api/admin/unpack-import')
      const r = await fetch('/api/admin/unpack-import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ wipe_input: true }),
      })
      const d = (await r.json().catch(() => null)) as any
      if (!r.ok) {
        setAdminMsg(`${t('dashboard.admin.errorPrefix')}${(d as any)?.detail || (d as any)?.message || `HTTP ${r.status}`}`)
        setBusy(null)
        return
      }
      startPolling()
    } catch (e: any) {
      setAdminMsg(`${t('dashboard.admin.errorPrefix')}${e?.message || String(e)}`)
      setBusy(null)
    }
  }

  const jobRunning = ['starting', 'unpack', 'import'].includes(job?.phase || '')
  const dataManagementBusy = !!(busy || loading || jobRunning)

  const emptyStats: DashboardStats = {
    chat_count: 0,
    message_count: 0,
    media_message_count: 0,
    media_file_count: 0,
    assigned_media: 0,
    unassigned_media: 0,
    snap_count: 0,
    memory_count: 0,
    first_message: null,
    last_message: null,
  }
  const s = stats ?? emptyStats
  const noData = !stats
  const fmtDate = (d: string | null | undefined) => formatDateShort(i18n.language, d)
  const fmtNum = (n: number | undefined) => formatNumber(i18n.language, n ?? 0)

  if (loading && !stats) return <div className="dashboardPage"><p className="muted">{t('dashboard.loading')}</p></div>

  return (
    <div className="dashboardPage">
      <h1>{t('nav.dashboard')}</h1>
      {noData && (
        <div className="dashNoDataBanner">
          {t('dashboard.noData')}
        </div>
      )}
      <p className="dashboardSubtitle">
        {t('dashboard.period', { from: fmtDate(s.first_message), to: fmtDate(s.last_message) })}
      </p>

      <div className="dashGrid">
        <Link to="/chats" className="dashCard dashCardLink">
          <div className="dashValue">{fmtNum(s.chat_count)}</div>
          <div className="dashLabel">{t('dashboard.labels.chats')}</div>
        </Link>
        <Link to="/stats" className="dashCard dashCardLink">
          <div className="dashValue">{fmtNum(s.message_count)}</div>
          <div className="dashLabel">{t('dashboard.labels.messages')}</div>
        </Link>
        <Link to="/media" className="dashCard dashCardLink">
          <div className="dashValue">{fmtNum(s.media_file_count)}</div>
          <div className="dashLabel">{t('dashboard.labels.chatMediaFiles')}</div>
        </Link>
        <div className="dashCard">
          <div className="dashValue">{fmtNum(s.media_message_count)}</div>
          <div className="dashLabel">{t('dashboard.labels.mediaMessages')}</div>
        </div>
        <div className="dashCard">
          <div className="dashValue">{fmtNum(s.assigned_media)}</div>
          <div className="dashLabel">{t('dashboard.labels.assignedMedia')}</div>
        </div>
        <div className="dashCard">
          <div className="dashValue">{fmtNum(s.unassigned_media)}</div>
          <div className="dashLabel">{t('dashboard.labels.unassigned')}</div>
        </div>
        <div className="dashCard">
          <div className="dashValue">{fmtNum(s.memory_count ?? 0)}</div>
          <div className="dashLabel">{t('dashboard.labels.memoriesFiles')}</div>
        </div>
        <div className="dashCard" title={t('dashboard.snapEntriesTitle')}>
          <div className="dashValue">{fmtNum(s.snap_count)}</div>
          <div className="dashLabel">{t('dashboard.labels.snapEntriesChats')}</div>
        </div>
      </div>

      <div className="dashSections">
        <section className="dashSection">
          <h2>{t('dashboard.quickAccess')}</h2>
          <div className="dashQuickLinks">
            <Link to="/chats" className="dashQuickLink">
              <span className="dashQuickIcon">💬</span>
              <span>{t('dashboard.quickLinks.browseChats')}</span>
            </Link>
            <Link to="/media" className="dashQuickLink">
              <span className="dashQuickIcon">📷</span>
              <span>{t('dashboard.quickLinks.chatMedia')}</span>
            </Link>
            <Link to="/stats" className="dashQuickLink">
              <span className="dashQuickIcon">📊</span>
              <span>{t('dashboard.quickLinks.insights')}</span>
            </Link>
            <Link to="/immich" className="dashQuickLink">
              <span className="dashQuickIcon">🖼️</span>
              <span>{t('dashboard.quickLinks.immichIntegration')}</span>
            </Link>
          </div>
        </section>

        <section className="dashSection">
          <h2>{t('dashboard.dataManagement')}</h2>

          <div className="dashQuickLinks">
            <button
              className="dashQuickLink"
              disabled={dataManagementBusy}
              onClick={runUnpackAndImport}
              title={t('dashboard.actions.unpackAndImportTitle')}
            >
              <span className="dashQuickIcon">🚀</span>
              <span>{t('dashboard.actions.unpackAndImportRecommended')}</span>
            </button>

            <button
              className="dashQuickLink"
              disabled={dataManagementBusy}
              onClick={() => runAdmin(
                '/api/admin/reset-immich',
                undefined,
                t('dashboard.confirm.immichFullReset')
              )}
            >
              <span className="dashQuickIcon">🗑️</span>
              <span>{t('dashboard.actions.immichFullReset')}</span>
            </button>
          </div>

          {dataManagementBusy && (
            <div className="dashProgressBanner">
              <div className="spinner" />
              <div>
                <strong>
                  {busy ? t('dashboard.progress.running', { label: busyLabel[busy] || busy }) : t('dashboard.progress.refreshing')}
                </strong>
                {jobRunning && (
                  <div style={{ marginTop: 8 }}>
                    <div className="dashProgressHint">{job?.message}</div>
                    {job && job.total > 0 && (
                      <div className="syncProgressBar" style={{ marginTop: 8 }}>
                        <div className="syncProgressLabel">
                          {formatNumber(i18n.language, job.current)} / {formatNumber(i18n.language, job.total)}
                          {' '}
                          ({Math.round((100 * job.current) / job.total)} %)
                        </div>
                        <div className="syncProgressTrack">
                          <div
                            className="syncProgressFill"
                            style={{ width: `${(100 * job.current) / job.total}%` }}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                )}
                <p className="dashProgressHint">
                  {busy ? t('dashboard.progress.hintWait') : t('dashboard.progress.hintReload')}
                </p>
              </div>
            </div>
          )}
          {adminMsg && (
            <div className={`dashResultMsg ${adminMsg.startsWith(t('dashboard.admin.errorPrefix')) ? 'dashResultError' : 'dashResultOk'}`}>
              {adminMsg}
            </div>
          )}
        </section>

        {immich && (
          <section className="dashSection">
            <h2>{t('dashboard.immichStatus.title')}</h2>
            <div className="dashImmichStatus">
              <div className="dashImmichRow">
                <span>{t('dashboard.immichStatus.server')}</span>
                <span className={`statusBadge ${immich.reachable ? 'ok' : 'warn'}`}>
                  {immich.reachable ? t('dashboard.immichStatus.reachable') : t('dashboard.immichStatus.notStarted')}
                </span>
              </div>
              {immich.configured && (
                <div className="dashImmichRow">
                  <span>{t('dashboard.immichStatus.configuration')}</span>
                  <span className={`statusBadge ${immich.key_valid ? 'ok' : 'warn'}`}>
                    {immich.key_valid ? t('dashboard.immichStatus.active') : t('dashboard.immichStatus.keyInvalid')}
                  </span>
                </div>
              )}
              {!immich.reachable && (
                <p className="dashImmichHint">
                  {t('dashboard.immichStatus.notRunningHint', { cpu: 'scripts/start-immich-cpu.bat', gpu: 'scripts/start-immich-gpu.bat' })}
                </p>
              )}
              {immich.reachable && (
                <Link to="/immich" className="btnPrimary dashImmichBtn">
                  {t('dashboard.immichStatus.manage')}
                </Link>
              )}
            </div>
          </section>
        )}
      </div>
    </div>
  )
}
