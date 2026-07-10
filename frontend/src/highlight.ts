// Sicheres Rendern von Meilisearch-Highlight-Snippets.
//
// WICHTIG: Wird von ChatPage.tsx und ChatsPage.tsx via dangerouslySetInnerHTML genutzt.
// Meilisearch liefert in `_formatted.text` den ORIGINALEN (nicht escapten) Nachrichtentext
// mit eingefügten Highlight-Tags. Da Nachrichtentexte von Dritten stammen können, muss der
// Text escaped werden. Nur die von Meili gesetzten <mark>-Tags dürfen als HTML durchgelassen
// werden. Aendert man hier die Pre/Post-Tags, muss das mit meili.py (highlightPreTag/
// highlightPostTag) uebereinstimmen.

const MEILI_PRE_TAG = '<mark>'
const MEILI_POST_TAG = '</mark>'

function escapeHtml(input: string): string {
  return input
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/**
 * Escaped den kompletten Snippet-Text und gibt danach ausschliesslich die von
 * Meilisearch gesetzten <mark>-Highlights wieder frei. Ergebnis ist sicher fuer
 * dangerouslySetInnerHTML.
 */
export function sanitizeHighlight(raw: string | null | undefined): string {
  const text = (raw ?? '').toString()
  if (!text) return ''

  const escaped = escapeHtml(text)

  const containedRawHtml = /&lt;(?!\/?mark&gt;)/.test(escaped)
  if (containedRawHtml) {
    console.debug(
      '[Debug highlight]: Potenziell gefaehrliches HTML im Suchtreffer neutralisiert.',
    )
  }

  return escaped
    .replaceAll(escapeHtml(MEILI_PRE_TAG), MEILI_PRE_TAG)
    .replaceAll(escapeHtml(MEILI_POST_TAG), MEILI_POST_TAG)
}
