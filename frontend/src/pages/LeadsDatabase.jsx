import { useEffect, useState } from 'react'
import { getLeads, uploadLeadsCsv, enrichLeads } from '../api'
import './LeadsDatabase.css'

function initials(lead) {
  const f = (lead.first_name || '').charAt(0)
  const l = (lead.last_name || '').charAt(0)
  return (f + l).toUpperCase() || '?'
}

function StatusPill({ value }) {
  if (!value) return null
  return <span className={`status-pill ${value}`}>{value.replace('_', ' ')}</span>
}

function DetailRow({ lead, colSpan }) {
  const points = lead.talking_points || []
  const priors = lead.prior_companies || []
  return (
    <tr className="leads-detail-row">
      <td colSpan={colSpan}>
        <div className="leads-detail">
          {lead.person_summary && <p className="leads-detail-summary">{lead.person_summary}</p>}
          <dl className="leads-detail-grid">
            {lead.seniority && <><dt>Seniority</dt><dd>{lead.seniority}</dd></>}
            {lead.tenure && <><dt>Tenure</dt><dd>{lead.tenure}</dd></>}
            {priors.length > 0 && <><dt>Previously</dt><dd>{priors.join(', ')}</dd></>}
            {lead.phone_source && <><dt>Phone source</dt><dd>{lead.phone_source}</dd></>}
            {lead.phone_confidence && <><dt>Phone confidence</dt><dd>{lead.phone_confidence}</dd></>}
            {lead.email_confidence != null && <><dt>Email confidence</dt><dd>{lead.email_confidence}/100</dd></>}
            {lead.research_summary && <><dt>Company</dt><dd>{lead.research_summary}</dd></>}
            {lead.fit_reason && <><dt>Why they fit</dt><dd>{lead.fit_reason}</dd></>}
          </dl>
          {points.length > 0 && (
            <>
              <div className="leads-detail-heading">Talking points</div>
              <ul className="leads-detail-points">
                {points.map((point) => <li key={point}>{point}</li>)}
              </ul>
            </>
          )}
          {(lead.profile_sources || []).length > 0 && (
            <div className="leads-detail-sources">
              {lead.profile_sources.map((url) => (
                <a key={url} href={url} target="_blank" rel="noreferrer">{new URL(url).hostname}</a>
              ))}
            </div>
          )}
          {!lead.person_summary && points.length === 0 && (
            <p className="leads-detail-empty">No prospect research yet — run the agent on this lead.</p>
          )}
        </div>
      </td>
    </tr>
  )
}

export default function LeadsDatabase({ active = true }) {
  const [leads, setLeads] = useState([])
  const [expanded, setExpanded] = useState(null)
  const [selected, setSelected] = useState(new Set())
  const [uploadResult, setUploadResult] = useState(null)
  const [enriching, setEnriching] = useState(false)

  async function refresh() {
    setLeads(await getLeads())
  }

  useEffect(() => {
    if (!active) return
    refresh()
    // Poll so leads the agent saves mid-run show up without a manual reload.
    const timer = setInterval(refresh, 5000)
    return () => clearInterval(timer)
  }, [active])

  function toggle(id) {
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  async function handleUpload(e) {
    const file = e.target.files[0]
    if (file) {
      const result = await uploadLeadsCsv(file)
      setUploadResult(result)
      await refresh()
    }
    e.target.value = ''
  }

  async function handleEnrich() {
    setEnriching(true)
    try {
      await enrichLeads(Array.from(selected))
      setSelected(new Set())
      await refresh()
    } finally {
      setEnriching(false)
    }
  }

  return (
    <div className="leads-page">
      <div className="leads-header">
        <div>
          <h1 className="leads-title">Leads Database</h1>
          <p className="leads-subtitle">{leads.length} lead{leads.length === 1 ? '' : 's'} tracked</p>
        </div>
      </div>

      <div className="leads-toolbar">
        <label className="leads-upload-label">
          Upload CSV
          <input className="leads-upload-input" type="file" accept=".csv" onChange={handleUpload} />
        </label>
        <button className="leads-enrich-button" onClick={handleEnrich} disabled={selected.size === 0 || enriching}>
          {enriching ? 'Enriching…' : `Enrich Selected${selected.size ? ` (${selected.size})` : ''}`}
        </button>
        {uploadResult && (
          <span className="leads-upload-result">
            Imported {uploadResult.inserted}
            {uploadResult.errors?.length ? `, ${uploadResult.errors.length} skipped` : ''}
          </span>
        )}
      </div>

      <div className="leads-table-wrap">
        <table className="leads-table">
          <thead>
            <tr>
              <th></th>
              <th>Name</th>
              <th>Title</th>
              <th>Company</th>
              <th>Domain</th>
              <th>Fit</th>
              <th>Email</th>
              <th>Email status</th>
              <th>Phone</th>
              <th>Phone status</th>
            </tr>
          </thead>
          <tbody>
            {leads.map((lead) => [
              <tr
                key={lead.id}
                className="leads-row"
                onClick={() => setExpanded(expanded === lead.id ? null : lead.id)}
              >
                <td onClick={(e) => e.stopPropagation()}>
                  {lead.status === 'pending' && (
                    <input
                      type="checkbox"
                      checked={selected.has(lead.id)}
                      onChange={() => toggle(lead.id)}
                    />
                  )}
                </td>
                <td>
                  <div className="leads-name-cell">
                    <span className="leads-avatar">{initials(lead)}</span>
                    {lead.first_name} {lead.last_name}
                    {lead.linkedin_url && (
                      <a
                        className="leads-linkedin"
                        href={lead.linkedin_url}
                        target="_blank"
                        rel="noreferrer"
                        title="LinkedIn profile"
                        onClick={(e) => e.stopPropagation()}
                      >in</a>
                    )}
                  </div>
                </td>
                <td>{lead.title || '—'}</td>
                <td>{lead.company}</td>
                <td>{lead.domain}</td>
                <td title={lead.fit_reason || ''}>
                  {lead.fit_score === null || lead.fit_score === undefined ? '—' : lead.fit_score}
                </td>
                <td>{lead.email || '—'}</td>
                <td><StatusPill value={lead.status} /></td>
                <td>{lead.phone || '—'}</td>
                <td><StatusPill value={lead.phone_status} /></td>
              </tr>,
              expanded === lead.id && <DetailRow key={`${lead.id}-detail`} lead={lead} colSpan={10} />,
            ])}
          </tbody>
        </table>
        {leads.length === 0 && (
          <div className="leads-empty-state">No leads yet. Ask the agent to find some, or upload a CSV.</div>
        )}
      </div>
    </div>
  )
}
