import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import Chat from './Chat'
import * as api from '../api'

describe('Chat page', () => {
  beforeEach(() => {
    vi.spyOn(api, 'sendChat')
  })

  it('shows Enrich/Done buttons when the response is paused', async () => {
    api.sendChat.mockResolvedValue({
      reply: 'Found 1 leads.', leads: [{ first_name: 'Jane' }],
      paused: true, gate_message: 'Found 1 leads. Reply enrich or done.',
    })

    render(<Chat />)
    fireEvent.change(screen.getByPlaceholderText(/message/i), { target: { value: 'find VPs' } })
    fireEvent.click(screen.getByText(/send/i))

    await waitFor(() => expect(screen.getByText('Enrich')).toBeInTheDocument())
    expect(screen.getByText('Done')).toBeInTheDocument()
  })

  it('posts the button value as the next message when clicked', async () => {
    api.sendChat
      .mockResolvedValueOnce({ reply: 'Found 1 leads.', leads: [], paused: true, gate_message: 'x' })
      .mockResolvedValueOnce({ reply: 'Enriched.', leads: [], paused: false, gate_message: null })

    render(<Chat />)
    fireEvent.change(screen.getByPlaceholderText(/message/i), { target: { value: 'find VPs' } })
    fireEvent.click(screen.getByText(/send/i))
    await waitFor(() => screen.getByText('Enrich'))

    fireEvent.click(screen.getByText('Enrich'))
    await waitFor(() => expect(api.sendChat).toHaveBeenLastCalledWith(
      'enrich', expect.any(String), expect.any(Function)
    ))
  })

  it('shows the graph panel and marks the current node from node events', async () => {
    api.sendChat.mockImplementation(async (message, threadId, onNodeEvent) => {
      onNodeEvent({ node: 'intent_node', data: { intent: 'find_leads' } })
      onNodeEvent({ node: 'find_node', data: {} })
      return { reply: 'Found 1 leads.', leads: [{ first_name: 'Jane' }], paused: true, gate_message: 'x' }
    })

    render(<Chat />)
    fireEvent.change(screen.getByPlaceholderText(/message/i), { target: { value: 'find VPs' } })
    fireEvent.click(screen.getByText(/send/i))

    await waitFor(() =>
      expect(screen.getByText('find_node').closest('.graph-node')).toHaveClass('completed')
    )
  })
})
