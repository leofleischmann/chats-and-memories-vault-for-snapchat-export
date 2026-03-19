/* eslint-disable no-console */
/**
 * i18n-Check (statisch):
 * - Ungenutzt: Key in de/en.json, aber nirgends als t('key') im frontend/src
 * - Fehlend: Key als t('key') im Code, aber nicht in de.json bzw. en.json
 *
 * Grenzen: Nur literale Strings in t('...') / i18n.t('...'). Dynamische Keys
 * (t(`x.${id}`)) und Hardcoded-Text in JSX ohne t() werden nicht erkannt.
 */
const fs = require('fs')
const path = require('path')

const LOCALES_DIR = __dirname
const SRC_DIR = path.resolve(LOCALES_DIR, '..') // frontend/src

function readJson(p) {
  return JSON.parse(fs.readFileSync(p, 'utf8'))
}

function flattenKeys(obj, prefix = '') {
  const out = []
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return out
  for (const [k, v] of Object.entries(obj)) {
    const next = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object' && !Array.isArray(v)) out.push(...flattenKeys(v, next))
    else out.push(next)
  }
  return out
}

function walkFiles(dir, exts, ignoreDirs) {
  const out = []
  const entries = fs.readdirSync(dir, { withFileTypes: true })
  for (const e of entries) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) {
      if (ignoreDirs.has(e.name)) continue
      out.push(...walkFiles(p, exts, ignoreDirs))
    } else if (e.isFile()) {
      const ext = path.extname(e.name).toLowerCase()
      if (exts.has(ext)) out.push(p)
    }
  }
  return out
}

function extractUsedKeysFromText(text) {
  const used = new Set()

  // Matches: t('a.b'), t("a.b"), t(`a.b`) and i18n.t('a.b') – only literal strings.
  const re = /(?:\b(?:i18n\.)?t)\(\s*(['"`])([^'"`]+)\1/g
  let m
  while ((m = re.exec(text)) !== null) {
    const key = (m[2] || '').trim()
    if (key) used.add(key)
  }

  return used
}

function setDiff(a, b) {
  const out = []
  for (const x of a) if (!b.has(x)) out.push(x)
  return out
}

function main() {
  const dePath = path.join(LOCALES_DIR, 'de.json')
  const enPath = path.join(LOCALES_DIR, 'en.json')
  if (!fs.existsSync(dePath) || !fs.existsSync(enPath)) {
    console.error('Fehler: de.json oder en.json nicht gefunden in:', LOCALES_DIR)
    process.exit(2)
  }

  const de = readJson(dePath)
  const en = readJson(enPath)
  const deKeys = new Set(flattenKeys(de))
  const enKeys = new Set(flattenKeys(en))
  const allLocaleKeys = new Set([...deKeys, ...enKeys])

  const files = walkFiles(
    SRC_DIR,
    new Set(['.ts', '.tsx', '.js', '.jsx']),
    new Set(['node_modules', 'dist', 'build', '.git', 'locales']),
  )

  const used = new Set()
  for (const f of files) {
    const text = fs.readFileSync(f, 'utf8')
    for (const k of extractUsedKeysFromText(text)) used.add(k)
  }

  const unusedAll = setDiff(allLocaleKeys, used).sort()
  const unusedDe = setDiff(deKeys, used).sort()
  const unusedEn = setDiff(enKeys, used).sort()

  // Keys die in einer Sprachdatei stehen, in der anderen aber nicht (Struktur-Drift)
  const onlyInEnNotDe = setDiff(enKeys, deKeys).sort()
  const onlyInDeNotEn = setDiff(deKeys, enKeys).sort()

  // „Andersrum“: im Code referenziert, in JSON fehlt
  const codeMissingInDe = setDiff(used, deKeys).sort()
  const codeMissingInEn = setDiff(used, enKeys).sort()
  const codeMissingAny = new Set([...codeMissingInDe, ...codeMissingInEn])

  console.log('i18n Check')
  console.log('==========')
  console.log(`Gefundene Dateien: ${files.length}`)
  console.log(`Verwendete Keys (statisch in t(...)): ${used.size}`)
  console.log('')

  console.log('1) Ungenutzt (in JSON, nicht im Code)')
  console.log('--------------------------------------')
  console.log(`Ungenutzt (vereinigt de/en): ${unusedAll.length}`)
  for (const k of unusedAll) console.log(`- ${k}`)
  console.log('')

  console.log(`Ungenutzt (nur de.json): ${unusedDe.length}`)
  for (const k of unusedDe) console.log(`- ${k}`)
  console.log('')

  console.log(`Ungenutzt (nur en.json): ${unusedEn.length}`)
  for (const k of unusedEn) console.log(`- ${k}`)
  console.log('')

  console.log('2) Fehlend (im Code, nicht in JSON)')
  console.log('--------------------------------------')
  console.log(`Fehlt in de.json: ${codeMissingInDe.length}`)
  for (const k of codeMissingInDe) console.log(`- ${k}`)
  console.log('')
  console.log(`Fehlt in en.json: ${codeMissingInEn.length}`)
  for (const k of codeMissingInEn) console.log(`- ${k}`)
  console.log('')

  if (onlyInEnNotDe.length || onlyInDeNotEn.length) {
    console.log('3) Nur in einer Sprachdatei (Struktur-Drift)')
    console.log('--------------------------------------')
    console.log(`In en.json, fehlt in de.json: ${onlyInEnNotDe.length}`)
    for (const k of onlyInEnNotDe) console.log(`- ${k}`)
    console.log('')
    console.log(`In de.json, fehlt in en.json: ${onlyInDeNotEn.length}`)
    for (const k of onlyInDeNotEn) console.log(`- ${k}`)
    console.log('')
  }

  const hasProblems =
    unusedAll.length > 0 || codeMissingAny.size > 0 || onlyInEnNotDe.length > 0 || onlyInDeNotEn.length > 0
  process.exit(hasProblems ? 1 : 0)
}

main()

