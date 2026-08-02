import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import LeadsDatabase from './LeadsDatabase'
import * as api from '../api'

describe('LeadsDatabase page', () => {
  beforeEach(() => {
    vi.spyOn(api, 'getLeads')
    vi.spyOn(api, 'enrichLeads')
  })

  it('renders leads in a table', async () => {
    api.getLeads.mockResolvedValue([
      { id: 1, first_name: 'Jane', last_name: 'Doe', company: 'Acme', domain: 'acme.com',
        email: null, status: 'pending', phone: null, phone_status: 'pending' },
    ])

    render(<LeadsDatabase />)
    await waitFor(() => expect(screen.getByText(/Jane/)).toBeInTheDocument())
    expect(screen.getByText('Acme')).toBeInTheDocument()
  })

  it('enriches selected pending leads', async () => {
    api.getLeads.mockResolvedValue([
      { id: 1, first_name: 'Jane', last_name: 'Doe', company: 'Acme', domain: 'acme.com',
        email: null, status: 'pending', phone: null, phone_status: 'pending' },
    ])
    api.enrichLeads.mockResolvedValue([
      { id: 1, first_name: 'Jane', last_name: 'Doe', company: 'Acme', domain: 'acme.com',
        email: 'jane@acme.com', status: 'verified', phone: null, phone_status: 'not_found' },
    ])

    render(<LeadsDatabase />)
    await waitFor(() => screen.getByText(/Jane/))
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByText(/enrich selected/i))

    await waitFor(() => expect(api.enrichLeads).toHaveBeenCalledWith([1]))
  })
})
