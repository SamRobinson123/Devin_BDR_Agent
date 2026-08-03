import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import Usage from './Usage'
import * as api from '../api'

vi.mock('../api')

const SUMMARY = {
  generated_at: '2026-08-02T12:00:00+00:00',
  hunter: {
    configured: true,
    plan_name: 'Growth',
    reset_date: '2026-08-27',
    quotas: [
      { id: 'verifications', label: 'Email verifications', used: 19000, available: 20000, remaining: 1000 },
      { id: 'searches', label: 'Domain searches', used: 500, available: 10000, remaining: 9500 },
    ],
    upgrade_url: 'https://hunter.io/pricing',
  },
  anthropic: {
    source: 'estimated',
    spend_usd: 4.25,
    model: 'claude-sonnet-4-5',
    billed: { configured: false, admin_keys_url: 'https://console.anthropic.com/settings/admin-keys' },
    estimated: {
      month: { requests: 12, input_tokens: 40000, output_tokens: 8000, cost_usd: 4.25 },
      daily: [{ day: '2026-08-01', cost_usd: 2.0 }, { day: '2026-08-02', cost_usd: 2.25 }],
      by_model: [{ model: 'claude-sonnet-4-5', cost_usd: 4.13 }],
      by_kind: [
        { kind: 'llm', requests: 12, cost_usd: 4.13 },
        { kind: 'verification', requests: 30, cost_usd: 0 },
      ],
    },
  },
  budget: { monthly_budget_usd: 20, spend_usd: 4.25, over_budget: false },
}

beforeEach(() => {
  vi.resetAllMocks()
  api.getUsage.mockResolvedValue(SUMMARY)
  api.getUsageSettings.mockResolvedValue({
    anthropic_admin_key_set: false,
    monthly_budget_usd: 20,
  })
  api.saveUsageSettings.mockResolvedValue({})
})

describe('Usage', () => {
  it('shows Hunter quota left with an upgrade link', async () => {
    render(<Usage />)
    expect(await screen.findByText('Email verifications')).toBeInTheDocument()
    expect(screen.getByText('1,000 left')).toBeInTheDocument()
    expect(screen.getByText('19,000 of 20,000 used')).toBeInTheDocument()
    expect(screen.getByText(/Upgrade plan/)).toHaveAttribute('href', 'https://hunter.io/pricing')
  })

  it('labels Claude spend as estimated when no admin key is saved', async () => {
    render(<Usage />)
    expect(await screen.findByText('$4.25')).toBeInTheDocument()
    expect(screen.getByText('Estimated locally')).toBeInTheDocument()
    expect(screen.getByText(/12 recorded calls/)).toBeInTheDocument()
  })

  it('shows billed spend when the admin key works', async () => {
    api.getUsage.mockResolvedValue({
      ...SUMMARY,
      anthropic: {
        ...SUMMARY.anthropic,
        source: 'billed',
        spend_usd: 31.4,
        billed: {
          configured: true,
          total_usd: 31.4,
          daily: [{ day: '2026-08-01', cost_usd: 31.4 }],
          by_model: [{ model: 'claude-sonnet-4-5', cost_usd: 30.0 }],
          usage_url: 'https://console.anthropic.com/settings/usage',
        },
      },
    })
    render(<Usage />)
    expect(await screen.findByText('$31.40')).toBeInTheDocument()
    expect(screen.getByText('Billed by Anthropic')).toBeInTheDocument()
  })

  it('breaks down calls by activity', async () => {
    render(<Usage />)
    expect(await screen.findByText('Hunter email verifications')).toBeInTheDocument()
    expect(screen.getByText('30')).toBeInTheDocument()
  })

  it('saves the admin key and budget, then reloads', async () => {
    render(<Usage />)
    await screen.findByText('$4.25')

    fireEvent.change(screen.getByPlaceholderText('sk-ant-admin…'), {
      target: { value: 'sk-ant-admin-secret' },
    })
    fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(api.saveUsageSettings).toHaveBeenCalledWith({
      anthropic_admin_key: 'sk-ant-admin-secret',
      monthly_budget_usd: 20,
    }))
    expect(await screen.findByText('Saved.')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('sk-ant-admin…')).toHaveValue('')
  })

  it('reports an unreachable server', async () => {
    api.getUsage.mockRejectedValue(new Error('Failed to fetch'))
    render(<Usage />)
    expect(await screen.findByText('Failed to fetch')).toBeInTheDocument()
  })
})
