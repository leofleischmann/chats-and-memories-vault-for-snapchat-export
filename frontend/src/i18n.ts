import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import en from './locales/en.json'
import de from './locales/de.json'

const STORAGE_KEY = 'ui_lang'

export function detectInitialLanguage(): 'en' | 'de' {
  const saved = (localStorage.getItem(STORAGE_KEY) || '').toLowerCase()
  if (saved === 'de' || saved === 'en') return saved
  return 'en'
}

export function setUiLanguage(lang: 'en' | 'de') {
  i18n.changeLanguage(lang)
  localStorage.setItem(STORAGE_KEY, lang)
  document.documentElement.lang = lang
}

i18n
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      de: { translation: de },
    },
    lng: detectInitialLanguage(),
    fallbackLng: 'en',
    interpolation: { escapeValue: false },
  })

document.documentElement.lang = i18n.language || 'en'

export default i18n

