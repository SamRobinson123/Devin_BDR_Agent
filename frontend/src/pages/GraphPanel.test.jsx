import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import GraphPanel from './GraphPanel'

describe('GraphPanel', () => {
  it('renders all five node names', () => {
    render(<GraphPanel path={[]} />)
    expect(screen.getByText('intent_node')).toBeInTheDocument()
    expect(screen.getByText('find_node')).toBeInTheDocument()
    expect(screen.getByText('human_gate')).toBeInTheDocument()
    expect(screen.getByText('enrich_node')).toBeInTheDocument()
    expect(screen.getByText('phone_node')).toBeInTheDocument()
  })

  it('marks nodes completed and current based on path', () => {
    render(<GraphPanel path={[
      { node: 'intent_node', status: 'completed' },
      { node: 'find_node', status: 'current' },
    ]} />)
    expect(screen.getByText('intent_node').closest('.graph-node')).toHaveClass('completed')
    expect(screen.getByText('find_node').closest('.graph-node')).toHaveClass('current')
    expect(screen.getByText('human_gate').closest('.graph-node')).toHaveClass('pending')
  })
})
