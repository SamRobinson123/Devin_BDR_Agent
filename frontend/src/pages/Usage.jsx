import { useEffect, useState } from 'react'
import { getUsage, getUsageSettings, saveUsageSettings } from '../api'
import './Usage.css'

const KIND_LABELS = {
  llm: 'Claude messages',
  web_search: 'Web searches',
}

const money = (value) => `$${Number(value || 0).toFixed(2)}`
const compact = (value) => Number(value || 0).toLocaleString()

function Meter({ used, available, tone }) {
  const pct = available > 0 ? Math.min((used / available) * 100, 100) : 0
  return (
    <div className="usage-meter" role="presentation">
      <div className="usage-meter-fill" data-tone={tone} style={{ width: `${pct}%` }} />
    </div>
  )
}

function SpendChart({ days }) {
  const points = days.filter((d) => d.day)
  if (points.length === 0) return <p className="usage-empty">No spend recorded yet.</p>
  const max = Math.max(...points.map((d) => d.cost_usd || 0), 0.0001)
  return (
    <div className="usage-chart" role="img" aria-label="Daily spend for the last 30 days">
      {points.map((d) => (
        <div className="usage-bar-slot" key={d.day} title={`${d.day}: ${money(d.cost_usd)}`}>
          <div
            className="usage-bar"
            style={{ height: `${Math.max((d.cost_usd / max) * 100, 2)}%` }}
          />
        </div>
      ))}
    </div>
  )
}

function ClaudeCard({ anthropic, budget }) {
  const billed = anthropic.billed || {}
  const estimated = anthropic.estimated || {}
  const days = anthropic.source === 'billed' ? billed.daily || [] : estimated.daily || []
  const models = anthropic.source === 'billed'
    ? (billed.by_model || []).map((m) => ({ model: m.model, cost_usd: m.cost_usd }))
    : (estimated.by_model || [])
  const month = estimated.month || {}

  return (
    <section className="usage-card">
      <div className="usage-card-head">
        <h2>Claude API</h2>
        <span className="usage-pill" data-variant={anthropic.source}>
          {anthropic.source === 'billed' ? 'Billed by Anthropic' : 'Estimated locally'}
        </span>
      </div>

      <div className="usage-figure">
        <span className="usage-figure-value">{money(anthropic.spend_usd)}</span>
        <span className="usage-figure-label">spent this month</span>
      </div>

      {billed.error && <p className="usage-error">{billed.error}</p>}
      {anthropic.source === 'estimated' && (
        <p className="usage-note">
          Priced from {compact(month.requests)} recorded calls
          ({compact(month.input_tokens)} in / {compact(month.output_tokens)} out tokens)
          at {anthropic.model} list prices. Add an admin key below for Anthropic&apos;s
          billed figure.
        </p>
      )}

      {budget.monthly_budget_usd > 0 && (
        <div className="usage-quota">
          <div className="usage-quota-head">
            <span className="usage-quota-label">Monthly budget</span>
            <span
              className="usage-quota-value"
              data-tone={budget.over_budget ? 'danger' : 'ok'}
            >
              {money(budget.spend_usd)} of {money(budget.monthly_budget_usd)}
            </span>
          </div>
          <Meter
            used={budget.spend_usd}
            available={budget.monthly_budget_usd}
            tone={budget.over_budget ? 'danger' : 'ok'}
          />
        </div>
      )}

      <h3 className="usage-subhead">Last 30 days</h3>
      <SpendChart days={days} />

      {models.length > 0 && (
        <table className="usage-table">
          <thead>
            <tr><th>Model</th><th>Cost</th></tr>
          </thead>
          <tbody>
            {models.map((m) => (
              <tr key={m.model || 'unknown'}>
                <td>{m.model || 'unknown'}</td>
                <td>{money(m.cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <a
        className="usage-link"
        href={billed.usage_url || 'https://console.anthropic.com/settings/usage'}
        target="_blank"
        rel="noreferrer"
      >
        Open Anthropic console →
      </a>
    </section>
  )
}

function ActivityCard({ byKind }) {
  if (!byKind?.length) return null
  return (
    <section className="usage-card">
      <div className="usage-card-head"><h2>Calls this month</h2></div>
      <table className="usage-table">
        <thead>
          <tr><th>Activity</th><th>Calls</th><th>Cost</th></tr>
        </thead>
        <tbody>
          {byKind.map((row) => (
            <tr key={row.kind}>
              <td>{KIND_LABELS[row.kind] || row.kind}</td>
              <td>{compact(row.requests)}</td>
              <td>{money(row.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

export default function Usage({ active = true }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [adminKey, setAdminKey] = useState('')
  const [budgetInput, setBudgetInput] = useState('')
  const [adminKeySet, setAdminKeySet] = useState(false)
  const [status, setStatus] = useState(null)

  async function refresh() {
    try {
      const [summary, settings] = await Promise.all([getUsage(), getUsageSettings()])
      setData(summary)
      setAdminKeySet(Boolean(settings.anthropic_admin_key_set))
      setBudgetInput(String(settings.monthly_budget_usd ?? ''))
      setError(null)
    } catch (err) {
      setError(err.message || 'Could not reach the server.')
    }
  }

  useEffect(() => {
    if (active) refresh()
  }, [active])

  async function handleSave() {
    setStatus('Saving…')
    await saveUsageSettings({
      anthropic_admin_key: adminKey,
      monthly_budget_usd: Number(budgetInput) || 0,
    })
    setAdminKey('')
    setStatus('Saved.')
    await refresh()
  }

  return (
    <div className="usage-page">
      <div className="usage-header">
        <div>
          <h1 className="usage-title">Usage &amp; spend</h1>
          <p className="usage-subtitle">
            What the agent has consumed, and how much room is left on each plan.
          </p>
        </div>
        <button className="usage-refresh" onClick={refresh}>Refresh</button>
      </div>

      {error && <p className="usage-error">{error}</p>}

      {data && (
        <>
          <div className="usage-grid">
            <ClaudeCard anthropic={data.anthropic} budget={data.budget} />
          </div>

          <ActivityCard byKind={data.anthropic.estimated?.by_kind} />

          <section className="usage-card">
            <div className="usage-card-head"><h2>Billing access</h2></div>
            <label className="usage-field">
              <span className="usage-field-label">Anthropic admin API key</span>
              <input
                type="password"
                placeholder="sk-ant-admin…"
                value={adminKey}
                onChange={(e) => setAdminKey(e.target.value)}
              />
              <span className="usage-field-hint">
                {adminKeySet
                  ? 'A key is saved. Leave blank to keep it.'
                  : 'Optional. Only an organisation admin key can read billed spend.'}
                {' '}
                <a
                  href={data.anthropic.billed?.admin_keys_url
                    || 'https://console.anthropic.com/settings/admin-keys'}
                  target="_blank"
                  rel="noreferrer"
                >
                  Create one
                </a>
              </span>
            </label>
            <label className="usage-field">
              <span className="usage-field-label">Monthly budget (USD)</span>
              <input
                type="number"
                min="0"
                step="1"
                value={budgetInput}
                onChange={(e) => setBudgetInput(e.target.value)}
              />
              <span className="usage-field-hint">0 hides the budget meter.</span>
            </label>
            <div className="usage-actions">
              <button className="usage-save" onClick={handleSave}>Save</button>
              {status && <span className="usage-status">{status}</span>}
            </div>
          </section>
        </>
      )}
    </div>
  )
}
