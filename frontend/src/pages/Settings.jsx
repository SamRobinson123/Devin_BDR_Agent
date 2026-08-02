import { useEffect, useState } from 'react'
import { getNotificationSettings, saveNotificationSettings, testNotification } from '../api'
import './Settings.css'

const EMPTY = {
  slack_enabled: false,
  slack_webhook_url: '',
  email_enabled: false,
  email_to: '',
  smtp_host: '',
  smtp_port: 587,
  smtp_username: '',
  smtp_password: '',
  notify_on_run_complete: true,
  notify_on_gate: true,
}

function Field({ label, hint, children }) {
  return (
    <label className="settings-field">
      <span className="settings-label">{label}</span>
      {children}
      {hint && <span className="settings-hint">{hint}</span>}
    </label>
  )
}

export default function Settings({ active = true }) {
  const [form, setForm] = useState(EMPTY)
  const [secretsSet, setSecretsSet] = useState({})
  const [status, setStatus] = useState(null)

  async function load() {
    const data = await getNotificationSettings()
    setSecretsSet({
      slack_webhook_url: data.slack_webhook_url_set,
      smtp_password: data.smtp_password_set,
    })
    setForm({ ...EMPTY, ...data, slack_webhook_url: '', smtp_password: '' })
  }

  useEffect(() => {
    if (active) load()
  }, [active])

  function set(key, value) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  async function handleSave() {
    await saveNotificationSettings(form)
    setStatus('Saved.')
    await load()
  }

  async function handleTest(channel) {
    setStatus(`Sending test to ${channel}…`)
    const result = await testNotification(channel)
    setStatus(result.ok ? `Test sent to ${channel}.` : `${channel} failed: ${result.error}`)
  }

  return (
    <div className="settings-page">
      <div className="settings-header">
        <h1 className="settings-title">Settings</h1>
        <p className="settings-subtitle">Connect Slack or email so the agent can send reports and reminders.</p>
      </div>

      <section className="settings-card">
        <div className="settings-card-head">
          <h2>Slack</h2>
          <label className="settings-toggle">
            <input
              type="checkbox"
              checked={form.slack_enabled}
              onChange={(e) => set('slack_enabled', e.target.checked)}
            />
            Enabled
          </label>
        </div>
        <Field
          label="Incoming webhook URL"
          hint={secretsSet.slack_webhook_url
            ? 'A webhook is saved. Leave blank to keep it.'
            : 'Create one at api.slack.com/messaging/webhooks'}
        >
          <input
            type="password"
            placeholder="https://hooks.slack.com/services/…"
            value={form.slack_webhook_url}
            onChange={(e) => set('slack_webhook_url', e.target.value)}
          />
        </Field>
        <button className="settings-test" onClick={() => handleTest('slack')}>Send test message</button>
      </section>

      <section className="settings-card">
        <div className="settings-card-head">
          <h2>Email</h2>
          <label className="settings-toggle">
            <input
              type="checkbox"
              checked={form.email_enabled}
              onChange={(e) => set('email_enabled', e.target.checked)}
            />
            Enabled
          </label>
        </div>
        <Field label="Send reports to">
          <input
            type="email"
            placeholder="you@company.com"
            value={form.email_to}
            onChange={(e) => set('email_to', e.target.value)}
          />
        </Field>
        <div className="settings-row">
          <Field label="SMTP host">
            <input
              placeholder="smtp.gmail.com"
              value={form.smtp_host}
              onChange={(e) => set('smtp_host', e.target.value)}
            />
          </Field>
          <Field label="Port">
            <input
              type="number"
              value={form.smtp_port}
              onChange={(e) => set('smtp_port', Number(e.target.value))}
            />
          </Field>
        </div>
        <Field label="SMTP username">
          <input
            value={form.smtp_username}
            onChange={(e) => set('smtp_username', e.target.value)}
          />
        </Field>
        <Field
          label="SMTP password"
          hint={secretsSet.smtp_password
            ? 'A password is saved. Leave blank to keep it.'
            : 'For Gmail, use an app password, not your account password.'}
        >
          <input
            type="password"
            value={form.smtp_password}
            onChange={(e) => set('smtp_password', e.target.value)}
          />
        </Field>
        <button className="settings-test" onClick={() => handleTest('email')}>Send test email</button>
      </section>

      <section className="settings-card">
        <h2>When to notify</h2>
        <label className="settings-toggle">
          <input
            type="checkbox"
            checked={form.notify_on_gate}
            onChange={(e) => set('notify_on_gate', e.target.checked)}
          />
          Remind me when the agent is waiting on my approval
        </label>
        <label className="settings-toggle">
          <input
            type="checkbox"
            checked={form.notify_on_run_complete}
            onChange={(e) => set('notify_on_run_complete', e.target.checked)}
          />
          Send a report when a run finishes
        </label>
      </section>

      <div className="settings-actions">
        <button className="settings-save" onClick={handleSave}>Save settings</button>
        {status && <span className="settings-status">{status}</span>}
      </div>
    </div>
  )
}
