import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import GraphPanel from './GraphPanel'

function node(name) {
  return document.querySelector(`[data-node="${name}"]`)
}

describe('GraphPanel', () => {
  it('renders every graph node', () => {
    const { container } = render(<GraphPanel path={[]} />)
    expect(container.querySelectorAll('.graph-node')).toHaveLength(10)
    expect(screen.getByText('Web search')).toBeInTheDocument()
    expect(screen.getByText('Your call')).toBeInTheDocument()
    expect(node('enrich_node')).toHaveClass('pending')
  })

  it('marks nodes completed and current based on path', () => {
    render(<GraphPanel path={[
      { node: 'intent_node', status: 'completed' },
      { node: 'find_node', status: 'current' },
    ]} />)
    expect(node('intent_node')).toHaveClass('completed')
    expect(node('find_node')).toHaveClass('current')
    expect(node('human_gate')).toHaveClass('pending')
  })

  it('animates the edge between the last completed and the current node', () => {
    const { container } = render(<GraphPanel path={[
      { node: 'intent_node', status: 'completed' },
      { node: 'find_node', status: 'current' },
    ]} />)
    expect(container.querySelectorAll('.graph-edge.active')).toHaveLength(1)
    expect(container.querySelector('.graph-edge-dot')).toBeInTheDocument()
  })
})
