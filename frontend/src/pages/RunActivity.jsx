import { useState } from 'react'
import './RunActivity.css'

const LABELS = {
  intent_node: 'Understood your request',
  find_node: 'Searched the web for prospects',
  dedupe_node: 'Removed duplicates',
  research_node: 'Researched companies',
  profile_node: 'Profiled people',
  score_node: 'Scored ICP fit',
  human_gate: 'Waiting on your call',
  enrich_node: 'Looked up contact info',
  draft_node: 'Wrote outreach drafts',
  notify_node: 'Sent notifications',
}

const ICONS = {
  intent_node: '🧭',
  find_node: '🔎',
  dedupe_node: '🧹',
  research_node: '🏢',
  profile_node: '👤',
  score_node: '🎯',
  human_gate: '✋',
  enrich_node: '✉️',
  draft_node: '✍️',
  notify_node: '🔔',
}

function name(lead) {
  return [lead.first_name, lead.last_name].filter(Boolean).join(' ') || lead.company || 'Unknown'
}

function count(items, singular) {
  const n = items.length
  return `${n} ${singular}${n === 1 ? '' : 's'}`
}

/** Turn a raw LangGraph node update into a one-line summary plus result rows. */
function summarize(node, data) {
  data = data || {}
  const leads = data.leads || data.enriched || []
  switch (node) {
    case 'intent_node':
      return { detail: `Intent: ${(data.intent || 'unknown').replace('_', ' ')}`, rows: [] }
    case 'find_node':
      return {
        detail: count(leads, 'prospect'),
        rows: leads.map((l) => ({
          key: name(l), title: name(l),
          text: [l.title, l.company, l.domain].filter(Boolean).join(' · '),
        })),
      }
    case 'dedupe_node': {
      const skipped = data.skipped || []
      return {
        detail: `${count(leads, 'new prospect')}${skipped.length ? `, ${skipped.length} already in database` : ''}`,
        rows: skipped.map((l) => ({ key: `s-${name(l)}`, title: name(l), text: 'already in database' })),
      }
    }
    case 'research_node':
      return {
        detail: count(leads, 'company brief'),
        rows: leads
          .filter((l) => l.research_summary || l.industry)
          .map((l) => ({
            key: `r-${name(l)}`, title: l.company || l.domain,
            text: [l.industry, l.employee_count, l.location, l.research_summary]
              .filter(Boolean).join(' · '),
          })),
      }
    case 'profile_node':
      return {
        detail: count(leads.filter((l) => l.person_summary || l.linkedin_url), 'profile'),
        rows: leads
          .filter((l) => l.person_summary || l.linkedin_url)
          .map((l) => ({
            key: `p-${name(l)}`, title: name(l),
            text: [l.title, l.seniority, l.person_summary].filter(Boolean).join(' · '),
            href: l.linkedin_url,
          })),
      }
    case 'score_node':
      return {
        detail: count(leads, 'prospect') + ' ranked by fit',
        rows: leads.map((l) => ({
          key: `sc-${name(l)}`, title: `${name(l)} — ${l.fit_score ?? '—'}`, text: l.fit_reason || '',
        })),
      }
    case 'human_gate':
      return { detail: 'Choose enrich, draft, or done', rows: [] }
    case 'enrich_node':
      return {
        detail: `${count(leads.filter((l) => l.email), 'email')}, ${count(leads.filter((l) => l.phone), 'phone number')}`,
        rows: leads.map((l) => ({
          key: `e-${name(l)}`, title: name(l),
          text: [l.email || 'no email found', l.phone || 'no phone found'].join(' · '),
          status: l.status,
        })),
      }
    case 'draft_node':
      return {
        detail: count(leads.filter((l) => l.draft_subject), 'draft'),
        rows: leads
          .filter((l) => l.draft_subject)
          .map((l) => ({
            key: `d-${name(l)}`, title: l.draft_subject, text: l.draft_body || '',
          })),
      }
    case 'notify_node':
      return { detail: 'Report sent to your connected channels', rows: [] }
    default:
      return { detail: '', rows: [] }
  }
}

function Step({ step, running }) {
  const { detail, rows } = summarize(step.node, step.data)
  const [open, setOpen] = useState(step.node === 'find_node')

  return (
    <div className="run-step" data-running={running}>
      <div className="run-step-head">
        <span className="run-step-icon" aria-hidden="true">{ICONS[step.node] || '•'}</span>
        <span className="run-step-title">{LABELS[step.node] || step.node}</span>
        {detail && <span className="run-step-detail">{detail}</span>}
        {rows.length > 0 && (
          <button className="run-step-toggle" onClick={() => setOpen((o) => !o)}>
            {open ? 'Hide' : 'Show'} results
          </button>
        )}
      </div>
      {open && rows.length > 0 && (
        <ul className="run-step-rows">
          {rows.map((row) => (
            <li key={row.key}>
              <span className="run-row-title">{row.title}</span>
              {row.status && <span className={`status-pill ${row.status}`}>{row.status.replace('_', ' ')}</span>}
              {row.text && <span className="run-row-text">{row.text}</span>}
              {row.href && (
                <a className="run-row-link" href={row.href} target="_blank" rel="noreferrer">profile</a>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function RunActivity({ steps, running }) {
  if (steps.length === 0) return null
  return (
    <div className="run-activity">
      <div className="run-activity-head">
        <span className="run-activity-title">
          {running ? 'Working…' : `Ran ${steps.length} step${steps.length === 1 ? '' : 's'}`}
        </span>
        <button
          className="run-activity-link"
          onClick={() => window.dispatchEvent(new CustomEvent('open-leads'))}
        >
          Open Leads Database
        </button>
      </div>
      {steps.map((step, i) => (
        <Step key={`${step.node}-${i}`} step={step} running={running && i === steps.length - 1} />
      ))}
    </div>
  )
}
