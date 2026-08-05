import { parseSseChunk } from './sse'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export async function sendChat(message, threadId, onNodeEvent) {
  let resp
  try {
    resp = await fetch(`${BASE_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, thread_id: threadId }),
    })
  } catch {
    throw new Error(`Can't reach the agent backend at ${BASE_URL}. Is the server running?`)
  }

  if (!resp.ok) {
    const detail = await resp.text().catch(() => '')
    throw new Error(`Agent request failed (${resp.status})${detail ? `: ${detail}` : ''}`)
  }
  if (!resp.body) throw new Error('Agent returned an empty response stream.')

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

  if (!result) throw new Error('The agent run ended without a result.')
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

export async function getNotificationSettings() {
  const resp = await fetch(`${BASE_URL}/settings/notifications`)
  return resp.json()
}

export async function saveNotificationSettings(settings) {
  const resp = await fetch(`${BASE_URL}/settings/notifications`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  })
  return resp.json()
}

export async function testNotification(channel) {
  const resp = await fetch(`${BASE_URL}/settings/notifications/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ channel }),
  })
  return resp.json()
}

export async function getUsage() {
  const resp = await fetch(`${BASE_URL}/usage`)
  return resp.json()
}

export async function getUsageSettings() {
  const resp = await fetch(`${BASE_URL}/settings/usage`)
  return resp.json()
}

export async function saveUsageSettings(settings) {
  const resp = await fetch(`${BASE_URL}/settings/usage`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  })
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
