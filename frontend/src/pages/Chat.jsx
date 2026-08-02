import { useEffect, useRef, useState } from 'react'
import { sendChat } from '../api'
import GraphPanel from './GraphPanel'
import './Chat.css'

function getThreadId() {
  let id = localStorage.getItem('thread_id')
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem('thread_id', id)
  }
  return id
}

export default function Chat() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [pending, setPending] = useState(null)
  const [sending, setSending] = useState(false)
  const [path, setPath] = useState([])
  const threadId = getThreadId()
  const scrollRef = useRef(null)

  useEffect(() => {
    scrollRef.current?.scrollIntoView?.({ behavior: 'smooth' })
  }, [messages, pending, sending])

  async function send(text) {
    if (!text.trim() || sending) return
    setSending(true)
    setPath([])
    setMessages((m) => [...m, { role: 'user', text }])
    try {
      const result = await sendChat(text, threadId, (evt) => {
        setPath((prev) => {
          const next = prev.map((p) => ({ ...p, status: 'completed' }))
          const already = next.find((p) => p.node === evt.node)
          if (already) {
            already.status = 'completed'
          } else {
            next.push({ node: evt.node, status: 'completed' })
          }

          if (evt.node === 'intent_node') {
            const branch = evt.data.intent === 'enrich_leads' ? 'enrich_node' : 'find_node'
            next.push({ node: branch, status: 'current' })
          } else if (evt.node === 'find_node') {
            next.push({ node: 'human_gate', status: 'current' })
          } else if (evt.node === 'human_gate') {
            next.push({ node: 'enrich_node', status: 'current' })
          } else if (evt.node === 'enrich_node') {
            next.push({ node: 'apollo_phone_node', status: 'current' })
          }
          return next
        })
      })
      setMessages((m) => [...m, { role: 'agent', text: result.reply, leads: result.leads }])
      setPending(result.paused ? result : null)
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="chat-page">
      <div className="chat-scroll">
        {messages.length === 0 ? (
          <div className="chat-empty">
            <h1>What leads are you looking for?</h1>
            <p>Ask me to find prospects or enrich a list you already have.</p>
          </div>
        ) : (
          <div className="chat-thread">
            {messages.map((m, i) => (
              <div key={i} className={`chat-row ${m.role}`}>
                {m.role === 'agent' && (
                  <div className="chat-avatar" aria-hidden="true">A</div>
                )}
                <div className="chat-bubble">
                  {m.text}
                  {m.leads?.length > 0 && (
                    <div className="chat-leads">
                      {m.leads.map((lead, li) => (
                        <div className="chat-lead-card" key={li}>
                          <div className="chat-lead-name">
                            {lead.first_name} {lead.last_name}
                          </div>
                          <div className="chat-lead-company">
                            {lead.company}{lead.domain ? ` · ${lead.domain}` : ''}
                          </div>
                          {(lead.email || lead.status) && (
                            <div className="chat-lead-detail">
                              {lead.email || 'no email'}
                              {lead.status && <span className={`status-pill ${lead.status}`}>{lead.status.replace('_', ' ')}</span>}
                            </div>
                          )}
                          {(lead.phone || lead.phone_status) && (
                            <div className="chat-lead-detail">
                              {lead.phone || 'no phone'}
                              {lead.phone_status && <span className={`status-pill ${lead.phone_status}`}>{lead.phone_status.replace('_', ' ')}</span>}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {pending && (
              <div className="chat-gate">
                <button
                  className="chat-gate-button primary"
                  onClick={() => send('enrich')}
                  disabled={sending}
                >
                  Enrich
                </button>
                <button
                  className="chat-gate-button"
                  onClick={() => send('done')}
                  disabled={sending}
                >
                  Done
                </button>
              </div>
            )}
            {sending && (
              <div className="chat-row agent">
                <div className="chat-avatar" aria-hidden="true">A</div>
                <div className="chat-thinking" role="status" aria-label="Agent is working">
                  <span></span><span></span><span></span>
                </div>
              </div>
            )}
            {path.length > 0 && <GraphPanel path={path} />}
            <div ref={scrollRef} />
          </div>
        )}
      </div>
      {!pending && (
        <div className="chat-composer">
          <div className="chat-composer-inner">
            <textarea
              className="chat-input"
              placeholder="Message the agent..."
              value={input}
              rows={1}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send(input)
                  setInput('')
                }
              }}
            />
            <button
              className="chat-send-button"
              disabled={!input.trim() || sending}
              onClick={() => { send(input); setInput('') }}
            >
              Send
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
