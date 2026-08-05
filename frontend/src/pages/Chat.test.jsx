import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import Chat from './Chat'
import * as api from '../api'

function ask(text = 'find VPs') {
  fireEvent.change(screen.getByPlaceholderText(/message/i), { target: { value: text } })
  fireEvent.click(screen.getByLabelText('Send'))
}

describe('Chat page', () => {
  beforeEach(() => {
    vi.spyOn(api, 'sendChat').mockReset()
  })

  it('shows Enrich/Done buttons when the response is paused', async () => {
    api.sendChat.mockResolvedValue({
      reply: 'Found 1 leads.', leads: [{ first_name: 'Jane' }],
      paused: true, gate_message: 'Found 1 leads. Reply enrich or done.',
    })

    render(<Chat />)
    ask()

    await waitFor(() => expect(screen.getByText('Enrich')).toBeInTheDocument())
    expect(screen.getByText('Done')).toBeInTheDocument()
  })

  it('posts the button value as the next message when clicked', async () => {
    api.sendChat
      .mockResolvedValueOnce({ reply: 'Found 1 leads.', leads: [], paused: true, gate_message: 'x' })
      .mockResolvedValueOnce({ reply: 'Enriched.', leads: [], paused: false, gate_message: null })

    render(<Chat />)
    ask()
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
    ask()

    await waitFor(() =>
      expect(document.querySelector('[data-node="find_node"]')).toHaveClass('completed')
    )
  })

  it('surfaces an error message when the backend is unreachable', async () => {
    api.sendChat.mockRejectedValue(
      new Error("Can't reach the agent backend at http://localhost:8000. Is the server running?")
    )

    render(<Chat />)
    ask()

    await waitFor(() =>
      expect(screen.getByText(/Can't reach the agent backend/i)).toBeInTheDocument()
    )
    // The composer must stay usable so the user can retry.
    expect(screen.getByPlaceholderText(/message/i)).toBeInTheDocument()
  })

  it('starts a new thread for each search but reuses it for gate replies', async () => {
    api.sendChat
      .mockResolvedValueOnce({ reply: 'Found 1 leads.', leads: [], paused: true, gate_message: 'x' })
      .mockResolvedValueOnce({ reply: 'Enriched.', leads: [], paused: false, gate_message: null })
      .mockResolvedValueOnce({ reply: 'Found 1 leads.', leads: [], paused: true, gate_message: 'x' })

    render(<Chat />)
    ask('find VPs at Acme')
    await waitFor(() => screen.getByText('Enrich'))
    const searchThread = api.sendChat.mock.calls[0][1]

    // Gate reply resumes on the same thread.
    fireEvent.click(screen.getByText('Enrich'))
    await waitFor(() => expect(screen.queryByText('Enrich')).not.toBeInTheDocument())
    expect(api.sendChat.mock.calls[1][1]).toBe(searchThread)

    // A brand-new search must NOT reuse the previous run's thread.
    ask('find CFOs at Globex')
    await waitFor(() => screen.getByText('Enrich'))
    expect(api.sendChat.mock.calls[2][1]).not.toBe(searchThread)
  })

  it('renders the search results from node events in the chat', async () => {
    api.sendChat.mockImplementation(async (message, threadId, onNodeEvent) => {
      onNodeEvent({
        node: 'find_node',
        data: { leads: [{ first_name: 'Ada', last_name: 'Lovelace', company: 'X', domain: 'x.io' }] },
      })
      return { reply: 'Found 1 leads.', leads: [], paused: true, gate_message: 'x' }
    })

    render(<Chat />)
    ask()

    await waitFor(() => expect(screen.getByText('Searched the web for prospects')).toBeInTheDocument())
    expect(screen.getByText('1 prospect')).toBeInTheDocument()
    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument()
    expect(screen.getByText('X · x.io')).toBeInTheDocument()
  })
})
