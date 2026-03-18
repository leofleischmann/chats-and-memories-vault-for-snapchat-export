import { Link, Route, Routes } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import DashboardPage from './pages/DashboardPage.tsx'
import ChatsPage from './pages/ChatsPage.tsx'
import ChatPage from './pages/ChatPage.tsx'
import StatsPage from './pages/StatsPage.tsx'
import MediaGalleryPage from './pages/MediaGalleryPage.tsx'
import ImmichPage from './pages/ImmichPage.tsx'
import './App.css'
import { setUiLanguage } from './i18n'

function App() {
  const { t, i18n } = useTranslation()
  const current = (i18n.language || 'en').startsWith('de') ? 'de' : 'en'

  return (
    <div className="appShell">
      <header className="topbar">
        <div className="brand">
          <Link to="/">{t('app.title')}</Link>
        </div>
        <nav className="nav">
          <Link to="/">{t('nav.dashboard')}</Link>
          <Link to="/chats">{t('nav.chats')}</Link>
          <Link to="/media">{t('nav.chatMedia')}</Link>
          <Link to="/stats">{t('nav.insights')}</Link>
          <Link to="/immich">{t('nav.immich')}</Link>
        </nav>
        <div className="topbarRight">
          <label className="topbarLang">
            <span className="topbarLangLabel">{t('settings.language')}</span>
            <select
              className="topbarLangSelect"
              value={current}
              onChange={(e) => setUiLanguage(e.target.value === 'de' ? 'de' : 'en')}
              aria-label={t('settings.language')}
            >
              <option value="en">{t('settings.english')}</option>
              <option value="de">{t('settings.german')}</option>
            </select>
          </label>
        </div>
      </header>
      <main className="main">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/chats" element={<ChatsPage />} />
          <Route path="/chat/:chatId" element={<ChatPage />} />
          <Route path="/media" element={<MediaGalleryPage />} />
          <Route path="/stats" element={<StatsPage />} />
          <Route path="/immich" element={<ImmichPage />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
