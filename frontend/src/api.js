import { parseSseChunk } from './sse'

const BASE_URL = 'http://localhost:8000'

export async function sendChat(message, threadId, onNodeEvent) {
  const resp = await fetch(`${BASE_URL}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, thread_id: threadId }),
  })

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const { events, remainder } = parseSseChunk(buffer)
    buffer = remainder
    for (const evt of events) {
      if (evt.event === 'node' && onNodeEvent) onNodeEvent(evt.data)
      if (evt.event === 'result') result = evt.data
    }
  }

  return result
}

export async function getLeads() {
  const resp = await fetch(`${BASE_URL}/leads`)
  return resp.json()
}

export async function uploadLeadsCsv(file) {
  const formData = new FormData()
  formData.append('file', file)
  const resp = await fetch(`${BASE_URL}/leads/upload`, { method: 'POST', body: formData })
  return resp.json()
}

export async function enrichLeads(leadIds) {
  const resp = await fetch(`${BASE_URL}/leads/enrich`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lead_ids: leadIds }),
  })
  return resp.json()
}
