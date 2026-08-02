import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import Settings from './Settings'
import * as api from '../api'

vi.mock('../api')

beforeEach(() => {
  vi.resetAllMocks()
  api.getNotificationSettings.mockResolvedValue({
    slack_enabled: true,
    slack_webhook_url_set: true,
    smtp_password_set: false,
    email_enabled: false,
    email_to: 'me@co.com',
    smtp_host: '',
    smtp_port: 587,
    smtp_username: '',
    notify_on_run_complete: true,
    notify_on_gate: true,
  })
  api.saveNotificationSettings.mockResolvedValue({})
})

describe('Settings', () => {
  it('loads settings and shows that a saved webhook is kept', async () => {
    render(<Settings />)
    expect(await screen.findByText(/A webhook is saved/)).toBeInTheDocument()
    expect(screen.getByDisplayValue('me@co.com')).toBeInTheDocument()
  })

  it('never prefills secret fields with stored values', async () => {
    render(<Settings />)
    await screen.findByText(/A webhook is saved/)
    expect(screen.getByPlaceholderText(/hooks.slack.com/)).toHaveValue('')
  })

  it('reports the result of a test notification', async () => {
    api.testNotification.mockResolvedValue({ ok: false, error: 'no webhook url configured' })
    render(<Settings />)
    await screen.findByText(/A webhook is saved/)

    fireEvent.click(screen.getByText('Send test message'))

    await waitFor(() =>
      expect(screen.getByText(/slack failed: no webhook url configured/)).toBeInTheDocument()
    )
  })
})
