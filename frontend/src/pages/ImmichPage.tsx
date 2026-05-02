import { useEffect, useState, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { formatNumber } from '../i18nFormat'

interface ImmichExternalSettings {
  external_immich_enabled: boolean
  external_immich_url: string
  api_key_configured: boolean
}

interface ImmichStatus {
  configured: boolean
  reachable: boolean
  key_valid: boolean
  url: string
  external_mode?: boolean
  external_settings?: ImmichExternalSettings
  gpu_profile_expected?: boolean
  backend_gpu_visible?: boolean
  ffmpeg_nvenc_available?: boolean
}

interface ImmichCredentials {
  configured: boolean
  external?: boolean
  external_url?: string
  admin_email?: string
  admin_password?: string
}

interface ImmichSyncSettings {
  combine_memories_overlay: boolean
  combine_memories_overlay_videos?: boolean
  memories_overlay_mode_locked?: boolean
}

interface SyncProgress {
  phase: string
  current: number
  total: number
  message: string
  error?: string
  result?: SyncResult
}

interface SyncResult {
  memories_uploaded: number
  memories_skipped: number
  memories_cache_skipped?: number
  memories_unsupported_mime?: number
  memories_upload_errors?: number
  shared_story_uploaded?: number
  shared_story_skipped?: number
  shared_story_cache_skipped?: number
  shared_story_unsupported_mime?: number
  shared_story_upload_errors?: number
  chat_media_uploaded: number
  chat_media_skipped: number
  chat_media_cache_skipped?: number
  chat_media_unsupported_mime?: number
  chat_media_upload_errors?: number
  albums_created: number
  errors: string[]
}

interface UnpackImportProgress {
  phase: string
  current: number
  total: number
  message: string
  error?: string | null
  result?: any
}

export default function ImmichPage() {
  const { t, i18n } = useTranslation()
  const [status, setStatus] = useState<ImmichStatus | null>(null)
  const [creds, setCreds] = useState<ImmichCredentials | null>(null)
  const [syncSettings, setSyncSettings] = useState<ImmichSyncSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [syncProgress, setSyncProgress] = useState<SyncProgress | null>(null)
  const [syncResult, setSyncResult] = useState<SyncResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showPassword, setShowPassword] = useState(false)
  const [confirmSync, setConfirmSync] = useState(false)
  const [combineOverlay, setCombineOverlay] = useState(false)
  const [combineOverlayVideos, setCombineOverlayVideos] = useState(false)
  const [unpackImport, setUnpackImport] = useState<UnpackImportProgress | null>(null)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [extEnabled, setExtEnabled] = useState(false)
  const [extUrl, setExtUrl] = useState('')
  const [extApiKey, setExtApiKey] = useState('')
  const [extSaving, setExtSaving] = useState(false)
  const [extTesting, setExtTesting] = useState(false)
  const [extFormMsg, setExtFormMsg] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const unpackPollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const checkStatus = useCallback(() => {
    setLoading(true)
    Promise.all([
      fetch('/api/immich/status').then(r => r.json()),
      fetch('/api/immich/credentials').then(r => r.json()),
      fetch('/api/immich/sync-settings').then(r => r.json()),
    ])
      .then(([s, c, ss]) => {
        setStatus(s)
        setCreds(c)
        setSyncSettings(ss)
        setCombineOverlay(Boolean(ss?.combine_memories_overlay))
        setCombineOverlayVideos(Boolean(ss?.combine_memories_overlay_videos))
        const ex = s?.external_settings
        setExtEnabled(Boolean(ex?.external_immich_enabled))
        setExtUrl(ex?.external_immich_url ?? '')
        setLoading(false)
      })
      .catch(() => {
        setStatus(null)
        setCreds(null)
        setSyncSettings(null)
        setExtEnabled(false)
        setExtUrl('')
        setLoading(false)
      })
  }, [])

  useEffect(() => { checkStatus() }, [checkStatus])

  useEffect(() => {
    // Keep the "Immich sync" UI locked while the app is still unpacking/importing.
    const poll = () => {
      fetch('/api/admin/unpack-import-progress')
        .then(r => r.ok ? r.json() : null)
        .then((p: UnpackImportProgress | null) => {
          if (!p) return
          setUnpackImport(p)
        })
        .catch(() => {})
    }
    poll()
    unpackPollRef.current = setInterval(poll, 1500)
    return () => {
      if (unpackPollRef.current) {
        clearInterval(unpackPollRef.current)
        unpackPollRef.current = null
      }
    }
  }, [])

  const importRunning = unpackImport ? ['starting', 'unpack', 'import'].includes(unpackImport.phase) : false

  const startPolling = useCallback(() => {
    if (pollRef.current) return
    const poll = () => {
      fetch('/api/immich/sync-progress')
        .then(r => r.json())
        .then((p: SyncProgress & { result?: SyncResult }) => {
          setSyncProgress({
            phase: p.phase,
            current: p.current,
            total: p.total,
            message: p.message,
            error: p.error,
            result: p.result,
          })
          if (p.phase === 'done' && p.result) {
            if (pollRef.current) {
              clearInterval(pollRef.current)
              pollRef.current = null
            }
            setSyncResult(p.result)
            setSyncing(false)
            setSyncProgress(null)
            checkStatus()
          } else if (p.phase === 'error') {
            if (pollRef.current) {
              clearInterval(pollRef.current)
              pollRef.current = null
            }
            setError(p.error || t('common.unknown'))
            setSyncing(false)
            setSyncProgress(null)
          } else {
            setSyncing(true)
          }
        })
        .catch(() => {})
    }
    poll()
    pollRef.current = setInterval(poll, 1500)
  }, [checkStatus])

  useEffect(() => {
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    // Resume polling after page reload if sync is still running
    fetch('/api/immich/sync-progress')
      .then(r => r.ok ? r.json() : null)
      .then((p: any) => {
        if (!p) return
        const running = !['idle', 'done', 'error'].includes(p.phase)
        if (running) {
          setSyncing(true)
          startPolling()
        }
      })
      .catch(() => {})
  }, [startPolling])

  const runSync = useCallback(() => {
    if (importRunning) return
    setConfirmSync(false)
    setSyncing(true)
    setSyncResult(null)
    setSyncProgress(null)
    setError(null)
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    fetch('/api/immich/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        combine_memories_overlay: combineOverlay,
        combine_memories_overlay_videos: combineOverlay && combineOverlayVideos,
      }),
    })
      .then(async r => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}))
          throw new Error(body.detail || `HTTP ${r.status}`)
        }
        return r.json()
      })
      .then(d => {
        if (!d.started) {
          setSyncing(false)
          return
        }
        startPolling()
      })
      .catch(e => { setError(e.message); setSyncing(false) })
  }, [checkStatus, combineOverlay, combineOverlayVideos, startPolling, importRunning])

  const saveExternalSettings = useCallback(() => {
    setExtSaving(true)
    setExtFormMsg(null)
    const payload: Record<string, unknown> = {
      external_immich_enabled: extEnabled,
      external_immich_url: extUrl.trim(),
    }
    if (extApiKey.trim())
      payload.external_immich_api_key = extApiKey.trim()

    fetch('/api/immich/external-settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then(async r => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}))
          throw new Error((body as { detail?: string }).detail || `HTTP ${r.status}`)
        }
        return r.json()
      })
      .then(() => {
        setExtFormMsg(t('immich.externalSaved'))
        setExtApiKey('')
        checkStatus()
      })
      .catch(e => setExtFormMsg(e instanceof Error ? e.message : String(e)))
      .finally(() => setExtSaving(false))
  }, [extEnabled, extUrl, extApiKey, checkStatus, t])

  const testExternalConnection = useCallback(() => {
    setExtTesting(true)
    setExtFormMsg(null)
    const url = extUrl.trim()
    const key = extApiKey.trim()
    if (!url || !key) {
      setExtFormMsg(t('immich.externalTestNeedBoth'))
      setExtTesting(false)
      return
    }
    fetch('/api/immich/test-external-connection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        external_immich_url: url,
        external_immich_api_key: key,
      }),
    })
      .then(r => r.json())
      .then((d: { ok?: boolean; message?: string }) => {
        setExtFormMsg(d.message || (d.ok ? t('immich.externalTestOk') : t('immich.externalTestFail')))
      })
      .catch(() => setExtFormMsg(t('immich.externalTestFail')))
      .finally(() => setExtTesting(false))
  }, [extUrl, extApiKey, t])

  if (loading) return <div className="pageContainer"><p>{t('immich.loading')}</p></div>

  const allGood = status?.configured && status?.reachable && status?.key_valid

  return (
    <div className="pageContainer">
      <h1>{t('immich.title')}</h1>

      {!status?.reachable && (
        <div className="immichNotRunning">
          <h2>{t('immich.notRunningTitle')}</h2>
          <p>
            {status?.external_mode
              ? t('immich.notRunningExternalBody')
              : t('immich.notRunningBody', { cpu: 'scripts/start-immich-cpu.bat', gpu: 'scripts/start-immich-gpu.bat' })}
          </p>
        </div>
      )}

      <>
          <section className="immichSection">
            <h2>{t('immich.connectionStatus')}</h2>
            <div className="immichStatusGrid">
              <div className="statusItem">
                <span className="statusLabel">{t('immich.immichServer')}</span>
                <span className={`statusBadge ${status?.reachable ? 'ok' : 'warn'}`}>
                  {status?.reachable ? t('immich.reachable') : t('immich.unreachable')}
                </span>
              </div>
              <div className="statusItem">
                <span className="statusLabel">{t('immich.autoConfig')}</span>
                <span className={`statusBadge ${allGood ? 'ok' : status?.configured ? 'ok' : 'warn'}`}>
                  {allGood
                    ? (status?.external_mode ? t('immich.externalActive') : t('immich.active'))
                    : status?.configured ? t('immich.keyInvalid') : t('immich.notSetUpYet')}
                </span>
              </div>
            </div>

            {!status?.configured && !status?.external_mode && (
              <div className="immichAutoHint">
                <p>
                  {t('immich.autoHint')}
                </p>
              </div>
            )}
            {Boolean(status?.external_mode) && !allGood && (
              <div className="immichAutoHint">
                <p>{t('immich.externalSetupHint')}</p>
              </div>
            )}
          </section>

          <section className="immichSection immichAdvanced">
            <button
              type="button"
              className="btnGhost immichAdvancedToggle"
              onClick={() => setAdvancedOpen(v => !v)}
              aria-expanded={advancedOpen}
            >
              {advancedOpen ? `▼ ${t('immich.advancedTitle')}` : `▶ ${t('immich.advancedTitle')}`}
            </button>
            {advancedOpen && (
              <div className="immichAdvancedBody">
                <p className="credHint">{t('immich.advancedIntro')}</p>
                <p className="credHint" style={{ marginTop: 8 }}>{t('immich.dockerHostHint')}</p>
                <label style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 14 }}>
                  <input
                    type="checkbox"
                    checked={extEnabled}
                    onChange={e => setExtEnabled(e.target.checked)}
                  />
                  <span>{t('immich.externalEnable')}</span>
                </label>
                <label className="immichAdvancedLabel">
                  {t('immich.externalUrl')}
                  <input
                    type="url"
                    className="immichAdvancedInput"
                    value={extUrl}
                    onChange={e => setExtUrl(e.target.value)}
                    placeholder={t('immich.externalUrlPlaceholder')}
                    disabled={!extEnabled}
                  />
                </label>
                <label className="immichAdvancedLabel">
                  {t('immich.externalApiKey')}
                  <input
                    type="password"
                    className="immichAdvancedInput"
                    autoComplete="off"
                    value={extApiKey}
                    onChange={e => setExtApiKey(e.target.value)}
                    placeholder={
                      Boolean(status?.external_settings?.api_key_configured) && extEnabled
                        ? t('immich.externalApiKeyPlaceholderKeep')
                        : t('immich.externalApiKeyPlaceholder')
                    }
                    disabled={!extEnabled}
                  />
                </label>
                <p className="muted" style={{ fontSize: '0.85rem', marginTop: 4 }}>
                  {t('immich.externalApiKeyKeepHint')}
                </p>
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 12 }}>
                  <button
                    type="button"
                    className="btnGhost"
                    disabled={extTesting || !extEnabled || !extUrl.trim()}
                    onClick={() => testExternalConnection()}
                  >
                    {extTesting ? t('immich.testing') : t('immich.testConnection')}
                  </button>
                  <button
                    type="button"
                    className="btnPrimary"
                    disabled={
                      extSaving
                      || (Boolean(extEnabled) && (
                        !extUrl.trim()
                        || (!extApiKey.trim() && !status?.external_settings?.api_key_configured)
                      ))
                    }
                    onClick={() => saveExternalSettings()}
                  >
                    {extSaving ? t('immich.saving') : t('immich.saveExternal')}
                  </button>
                </div>
                {extFormMsg && (
                  <p style={{ marginTop: 12 }} className="muted">{extFormMsg}</p>
                )}
              </div>
            )}
          </section>

          {creds?.configured && (
            <section className="immichSection">
              <h2>{t('immich.credentialsTitle')}</h2>
              {creds.external ? (
                <>
                  <p className="credHint">{t('immich.externalCredentialsHint')}</p>
                  <div className="credGrid">
                    <div className="credItem">
                      <span className="credLabel">{t('immich.externalUrl')}</span>
                      <code className="credValue">{creds.external_url || status?.url}</code>
                    </div>
                  </div>
                  <a
                    href={status?.url || '#'}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btnPrimary immichOpenBtn"
                  >
                    {t('immich.openUi')}
                  </a>
                </>
              ) : (
                <>
                  <p className="credHint">{t('immich.credentialsHint')}</p>
                  <div className="credGrid">
                    <div className="credItem">
                      <span className="credLabel">{t('immich.email')}</span>
                      <code className="credValue">{creds.admin_email}</code>
                    </div>
                    <div className="credItem">
                      <span className="credLabel">{t('immich.password')}</span>
                      <div className="credPasswordRow">
                        <code className="credValue">
                          {showPassword ? creds.admin_password : '••••••••••••••••'}
                        </code>
                        <button
                          className="btnGhost btnSmall"
                          onClick={() => setShowPassword(v => !v)}
                        >
                          {showPassword ? t('immich.hide') : t('immich.show')}
                        </button>
                      </div>
                    </div>
                  </div>
                  <a
                    href={status?.url || 'http://localhost:2283'}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btnPrimary immichOpenBtn"
                  >
                    {t('immich.openUi')}
                  </a>
                </>
              )}
            </section>
          )}

          <section className="immichSection">
            <h2>{t('immich.mediaSync')}</h2>

            <div className="syncWarningBox">
              <strong>{t('immich.syncNoteTitle')}</strong> {t('immich.syncNoteBody')}
              {!allGood && !status?.external_mode && ` ${t('immich.syncNoteAutoSetup')}`}
            </div>

            {status?.gpu_profile_expected && !status?.backend_gpu_visible && (
              <div className="syncWarningBox" style={{ marginTop: 12 }}>
                <strong>{t('immich.gpuWarningTitle')}</strong> {t('immich.gpuWarningBody')}
              </div>
            )}

            {importRunning && (
              <div className="syncWarningBox" style={{ marginTop: 12, opacity: 0.95 }}>
                <strong>Import läuft noch:</strong> {unpackImport?.message || 'Bitte warten…'}
              </div>
            )}

            <p style={{ marginTop: 12 }}>
              {t('immich.syncBody')}
            </p>

            {!syncing && !confirmSync && (
              <button
                onClick={() => setConfirmSync(true)}
                className="btnPrimary"
                disabled={importRunning || !status?.reachable}
                title={!status?.reachable ? t('immich.syncNeedsReachable') : undefined}
              >
                {t('immich.startSync')}
              </button>
            )}

            {confirmSync && (
              <div className="syncConfirmDialog">
                <p>
                  <strong>{t('immich.confirmTitle')}</strong> {t('immich.confirmBody')}
                </p>
                {syncSettings?.memories_overlay_mode_locked ? (
                  <div style={{ marginTop: 12 }}>
                    <strong>{t('immich.memoriesModeLocked')}</strong>{' '}
                    {syncSettings?.combine_memories_overlay ? t('immich.withOverlay') : t('immich.withoutOverlay')}
                    {syncSettings?.combine_memories_overlay && (
                      <>
                        {' · '}
                        {syncSettings?.combine_memories_overlay_videos
                          ? t('immich.withOverlayVideos')
                          : t('immich.withoutOverlayVideos')}
                      </>
                    )}
                    <div style={{ opacity: 0.85, marginTop: 6 }}>
                      {t('immich.memoriesModeLockedHint')}
                    </div>
                  </div>
                ) : (
                  <>
                    <label style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 12 }}>
                      <input
                        type="checkbox"
                        checked={combineOverlay}
                        onChange={e => setCombineOverlay(e.target.checked)}
                      />
                      <span>
                        {t('immich.combineOverlay')}
                        {syncSettings ? ` ${t('immich.remembered')}` : ''}
                      </span>
                    </label>
                    <label
                      style={{
                        display: 'flex',
                        gap: 10,
                        alignItems: 'center',
                        marginTop: 10,
                        opacity: combineOverlay ? 1 : 0.65,
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={combineOverlay && combineOverlayVideos}
                        disabled={!combineOverlay}
                        onChange={e => setCombineOverlayVideos(e.target.checked)}
                      />
                      <span>{t('immich.combineOverlayVideos')}</span>
                    </label>
                    <div style={{ marginTop: 6, opacity: 0.85, fontSize: 13 }}>
                      {t('immich.overlayVideoFastModeHint')}
                    </div>
                  </>
                )}
                <div className="syncConfirmActions">
                  <button onClick={runSync} className="btnPrimary" disabled={importRunning || !status?.reachable}>
                    {t('immich.confirmYes')}
                  </button>
                  <button onClick={() => setConfirmSync(false)} className="btnGhost">
                    {t('common.cancel')}
                  </button>
                </div>
              </div>
            )}

            {syncing && (
              <div className="syncProgress">
                <div className="spinner" />
                <p>
                  {!status?.configured
                    ? t('immich.setupAndTransfer')
                    : t('immich.transfer')}
                  {' '}{t('immich.patience')}
                </p>
                {syncProgress && syncProgress.total > 0 && (
                  <div className="syncProgressBar">
                    <div className="syncProgressLabel">
                      {syncProgress.phase === 'memories'
                        ? t('immich.progressPhase.memories')
                        : syncProgress.phase === 'chat_media'
                          ? t('immich.progressPhase.chat_media')
                          : syncProgress.phase === 'overlay_combine'
                            ? t('immich.progressPhase.overlay_combine')
                          : syncProgress.phase}
                      {' '}
                      {formatNumber(i18n.language, syncProgress.current)} / {formatNumber(i18n.language, syncProgress.total)}
                      {' '}
                      ({Math.round((100 * syncProgress.current) / syncProgress.total)} %)
                    </div>
                    <div className="syncProgressTrack">
                      <div
                        className="syncProgressFill"
                        style={{ width: `${(100 * syncProgress.current) / syncProgress.total}%` }}
                      />
                    </div>
                  </div>
                )}
              </div>
            )}

            {error && (
              <div className="syncError">
                <strong>{t('immich.errorPrefix')}</strong> {error}
              </div>
            )}

            {syncResult && (
              <div className="syncResults">
                <h3>{t('immich.done')}</h3>
                <div className="resultGrid">
                  <div className="resultCard">
                    <div className="resultLabel">{t('immich.results.memUploaded')}</div>
                    <div className="resultValue">{syncResult.memories_uploaded}</div>
                  </div>
                  <div className="resultCard">
                    <div className="resultLabel">{t('immich.results.memSkipped')}</div>
                    <div className="resultValue">{syncResult.memories_skipped}</div>
                  </div>
                  <div className="resultCard">
                    <div className="resultLabel">{t('immich.results.memCacheSkipped')}</div>
                    <div className="resultValue">{syncResult.memories_cache_skipped ?? 0}</div>
                  </div>
                  <div className="resultCard">
                    <div className="resultLabel">{t('immich.results.memImmichSkipped')}</div>
                    <div className="resultValue">{Math.max(0, syncResult.memories_skipped - (syncResult.memories_cache_skipped ?? 0))}</div>
                  </div>

                  <div className="resultCard">
                    <div className="resultLabel">{t('immich.results.sharedUploaded')}</div>
                    <div className="resultValue">{syncResult.shared_story_uploaded ?? 0}</div>
                  </div>
                  <div className="resultCard">
                    <div className="resultLabel">{t('immich.results.sharedSkipped')}</div>
                    <div className="resultValue">{syncResult.shared_story_skipped ?? 0}</div>
                  </div>
                  <div className="resultCard">
                    <div className="resultLabel">{t('immich.results.sharedCacheSkipped')}</div>
                    <div className="resultValue">{syncResult.shared_story_cache_skipped ?? 0}</div>
                  </div>
                  <div className="resultCard">
                    <div className="resultLabel">{t('immich.results.sharedImmichSkipped')}</div>
                    <div className="resultValue">
                      {Math.max(0, (syncResult.shared_story_skipped ?? 0) - (syncResult.shared_story_cache_skipped ?? 0))}
                    </div>
                  </div>
                  <div className="resultCard">
                    <div className="resultLabel">{t('immich.results.chatUploaded')}</div>
                    <div className="resultValue">{syncResult.chat_media_uploaded}</div>
                  </div>
                  <div className="resultCard">
                    <div className="resultLabel">{t('immich.results.chatSkipped')}</div>
                    <div className="resultValue">{syncResult.chat_media_skipped}</div>
                  </div>
                  <div className="resultCard">
                    <div className="resultLabel">{t('immich.results.chatCacheSkipped')}</div>
                    <div className="resultValue">{syncResult.chat_media_cache_skipped ?? 0}</div>
                  </div>
                  <div className="resultCard">
                    <div className="resultLabel">{t('immich.results.chatImmichSkipped')}</div>
                    <div className="resultValue">{Math.max(0, syncResult.chat_media_skipped - (syncResult.chat_media_cache_skipped ?? 0))}</div>
                  </div>
                  <div className="resultCard">
                    <div className="resultLabel">{t('immich.results.albumsCreated')}</div>
                    <div className="resultValue">{syncResult.albums_created}</div>
                  </div>
                </div>
                {syncResult.errors.length > 0 && (
                  <div className="syncWarnings">
                    <h4>{t('immich.warnings', { count: syncResult.errors.length })}</h4>
                    <div className="muted" style={{ marginBottom: 10, fontSize: '0.9rem' }}>
                      {t('immich.warningsBreakdown', {
                        unsupported:
                          (syncResult.memories_unsupported_mime ?? 0) +
                          (syncResult.shared_story_unsupported_mime ?? 0) +
                          (syncResult.chat_media_unsupported_mime ?? 0),
                        uploadErrors:
                          (syncResult.memories_upload_errors ?? 0) +
                          (syncResult.shared_story_upload_errors ?? 0) +
                          (syncResult.chat_media_upload_errors ?? 0),
                      })}
                    </div>
                    <ul>
                      {syncResult.errors.slice(0, 20).map((e, i) => <li key={i}>{e}</li>)}
                      {syncResult.errors.length > 20 && <li>{t('immich.warningsMore', { count: syncResult.errors.length - 20 })}</li>}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </section>
      </>
    </div>
  )
}
