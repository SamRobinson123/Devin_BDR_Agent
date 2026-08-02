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

export default function LeadsDatabase({ active = true }) {
  const [leads, setLeads] = useState([])
  const [selected, setSelected] = useState(new Set())
  const [uploadResult, setUploadResult] = useState(null)
  const [enriching, setEnriching] = useState(false)

  async function refresh() {
    setLeads(await getLeads())
  }

  useEffect(() => {
    if (active) refresh()
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
              <th>Company</th>
              <th>Domain</th>
              <th>Email</th>
              <th>Email status</th>
              <th>Phone</th>
              <th>Phone status</th>
            </tr>
          </thead>
          <tbody>
            {leads.map((lead) => (
              <tr key={lead.id}>
                <td>
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
                  </div>
                </td>
                <td>{lead.company}</td>
                <td>{lead.domain}</td>
                <td>{lead.email || '—'}</td>
                <td><StatusPill value={lead.status} /></td>
                <td>{lead.phone || '—'}</td>
                <td><StatusPill value={lead.phone_status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {leads.length === 0 && (
          <div className="leads-empty-state">No leads yet. Ask the agent to find some, or upload a CSV.</div>
        )}
      </div>
    </div>
  )
}
