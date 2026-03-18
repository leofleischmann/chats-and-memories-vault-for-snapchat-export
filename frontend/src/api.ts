export type Chat = {
  chat_id: string
  title: string
  text_message_count: number
  message_count: number
  first_ts?: string | null
  last_ts?: string | null
}

export type Message = {
  message_id: string
  chat_id: string
  ts_utc?: string | null
  sender?: string | null
  is_sender?: number | boolean
  type: string
  text: string
  ordinal_in_chat: number
  is_saved: number | boolean
  media_id?: string | null
  media_filename?: string | null
}

export type MediaFile = {
  filename: string
  file_date: string | null
  extension: string
  media_type: 'image' | 'video' | 'audio' | 'other'
  chat_id?: string | null
  chat_title?: string | null
  message_id?: string | null
  sender?: string | null
  ts_utc?: string | null
  msg_type?: string | null
}

export type MediaChat = {
  chat_id: string
  title: string
  media_count: number
}

export function mediaUrl(filename: string): string {
  return `/api/media/files/${encodeURIComponent(filename)}`
}

export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(path)
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return (await r.json()) as T
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return (await r.json()) as T
}

