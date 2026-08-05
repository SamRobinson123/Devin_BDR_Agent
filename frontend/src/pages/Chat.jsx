import { useEffect, useRef, useState } from 'react'
import { sendChat } from '../api'
import GraphPanel from './GraphPanel'
import RunActivity from './RunActivity'
import './Chat.css'

const NEXT_NODE = {
  find_node: 'dedupe_node',
  dedupe_node: 'research_node',
  research_node: 'profile_node',
  profile_node: 'score_node',
  score_node: 'human_gate',
  human_gate: 'enrich_node',
  enrich_node: 'phone_node',
}

const SUGGESTIONS = [
  'Find VPs of Sales at Series A fintech startups',
  'Find heads of RevOps at US logistics companies',
  'Enrich the leads already in my database',
]

function getThreadId() {
  let id = localStorage.getItem('thread_id')
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem('thread_id', id)
  }
  return id
}

function LeadCard({ lead }) {
  return (
    <div className="chat-lead-card">
      <div className="chat-lead-name">
        {lead.first_name} {lead.last_name}
        {lead.linkedin_url && (
          <a className="chat-lead-linkedin" href={lead.linkedin_url} target="_blank" rel="noreferrer">in</a>
        )}
      </div>
      <div className="chat-lead-company">
        {[lead.title, lead.company].filter(Boolean).join(' · ')}
        {lead.domain ? ` · ${lead.domain}` : ''}
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
      {lead.fit_score !== null && lead.fit_score !== undefined && (
        <div className="chat-lead-detail" title={lead.fit_reason || ''}>ICP fit {lead.fit_score}</div>
      )}
      {lead.draft_subject && (
        <div className="chat-lead-draft">
          <div className="chat-lead-draft-subject">{lead.draft_subject}</div>
          <div className="chat-lead-draft-body">{lead.draft_body}</div>
        </div>
      )}
    </div>
  )
}

export default function Chat() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [pending, setPending] = useState(null)
  const [sending, setSending] = useState(false)
  const [path, setPath] = useState([])
  const [steps, setSteps] = useState([])
  const [railOpen, setRailOpen] = useState(true)
  const threadId = getThreadId()
  const scrollRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    scrollRef.current?.scrollIntoView?.({ behavior: 'smooth' })
  }, [messages, steps, pending, sending])

  function autoGrow(el) {
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }

  async function send(text, options = {}) {
    if (!text.trim() || sending) return
    setSending(true)
    setPath([])
    setSteps([])
    setMessages((m) => [...m, { role: 'user', text }])
    const collected = []
    try {
      const result = await sendChat(text, threadId, (evt) => {
        collected.push({ node: evt.node, data: evt.data })
        setSteps([...collected])
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
          } else if (evt.node === 'phone_node') {
            if (options.drafting) next.push({ node: 'draft_node', status: 'current' })
            else next.push({ node: 'notify_node', status: 'current' })
          } else if (evt.node === 'draft_node') {
            next.push({ node: 'notify_node', status: 'current' })
          } else if (NEXT_NODE[evt.node]) {
            next.push({ node: NEXT_NODE[evt.node], status: 'current' })
          }
          return next
        })
      })
      setSteps([])
      setMessages((m) => [...m, {
        role: 'agent', text: result.reply, leads: result.leads, steps: collected,
      }])
      setPending(result.paused ? result : null)
      if (!result.paused) {
        setPath((prev) => prev.filter((p) => p.status === 'completed'))
      }
    } catch (err) {
      setSteps([])
      setPath([])
      setMessages((m) => [...m, {
        role: 'agent', error: true,
        text: err?.message || 'Something went wrong reaching the agent.',
      }])
    } finally {
      setSending(false)
    }
  }

  function submit() {
    send(input)
    setInput('')
    autoGrow(inputRef.current)
  }

  const currentStep = path.find((p) => p.status === 'current')

  return (
    <div className="chat-page" data-rail={railOpen}>
      <div className="chat-main">
        <header className="chat-topbar">
          <div className="chat-topbar-title">BDR Agent</div>
          {sending && currentStep && (
            <span className="chat-topbar-status">
              <span className="chat-topbar-dot" aria-hidden="true" />
              {currentStep.node.replace(/_node$/, '').replace('_', ' ')}
            </span>
          )}
          <button
            className="chat-rail-toggle"
            onClick={() => setRailOpen((o) => !o)}
            aria-pressed={railOpen}
          >
            {railOpen ? 'Hide run graph' : 'Show run graph'}
          </button>
        </header>

        <div className="chat-scroll">
          {messages.length === 0 && !sending ? (
            <div className="chat-empty">
              <h1>What leads are you looking for?</h1>
              <p>Ask me to find prospects or enrich a list you already have.</p>
              <div className="chat-suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="chat-suggestion" onClick={() => send(s)}>{s}</button>
                ))}
              </div>
            </div>
          ) : (
            <div className="chat-thread">
              {messages.map((m, i) => (
                <div key={i} className={`chat-row ${m.role}`}>
                  {m.role === 'agent' && <div className="chat-avatar" aria-hidden="true">A</div>}
                  <div className={`chat-bubble${m.error ? ' error' : ''}`}>
                    {m.steps?.length > 0 && <RunActivity steps={m.steps} running={false} />}
                    {m.text}
                    {m.leads?.length > 0 && (
                      <div className="chat-leads">
                        {m.leads.map((lead, li) => <LeadCard key={li} lead={lead} />)}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {sending && (
                <div className="chat-row agent">
                  <div className="chat-avatar" aria-hidden="true">A</div>
                  <div className="chat-bubble">
                    <RunActivity steps={steps} running />
                    <div className="chat-thinking" role="status" aria-label="Agent is working">
                      <span></span><span></span><span></span>
                    </div>
                  </div>
                </div>
              )}
              {pending && !sending && (
                <div className="chat-gate">
                  <button className="chat-gate-button primary" onClick={() => send('enrich')} disabled={sending}>
                    Enrich
                  </button>
                  <button className="chat-gate-button" onClick={() => send('draft', { drafting: true })} disabled={sending}>
                    Enrich + Draft
                  </button>
                  <button className="chat-gate-button" onClick={() => send('done')} disabled={sending}>
                    Done
                  </button>
                </div>
              )}
              <div ref={scrollRef} />
            </div>
          )}
        </div>

        {!pending && (
          <div className="chat-composer">
            <div className="chat-composer-inner">
              <textarea
                ref={inputRef}
                className="chat-input"
                placeholder="Message the agent..."
                value={input}
                rows={1}
                onChange={(e) => { setInput(e.target.value); autoGrow(e.target) }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    submit()
                  }
                }}
              />
              <button
                className="chat-send-button"
                aria-label="Send"
                disabled={!input.trim() || sending}
                onClick={submit}
              >
                ↑
              </button>
            </div>
            <div className="chat-composer-hint">
              Leads found in a run are saved to your Leads Database automatically.
            </div>
          </div>
        )}
      </div>

      <aside className="chat-rail" hidden={!railOpen}>
        <div className="chat-rail-head">Agent run</div>
        <GraphPanel path={path} />
      </aside>
    </div>
  )
}
