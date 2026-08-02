import { describe, it, expect } from 'vitest'
import { parseSseChunk } from './sse'

describe('parseSseChunk', () => {
  it('parses a single complete event', () => {
    const text = 'event: node\ndata: {"node":"intent_node"}\n\n'
    const { events, remainder } = parseSseChunk(text)
    expect(events).toEqual([{ event: 'node', data: { node: 'intent_node' } }])
    expect(remainder).toBe('')
  })

  it('parses multiple events in one chunk', () => {
    const text =
      'event: node\ndata: {"node":"intent_node"}\n\n' +
      'event: node\ndata: {"node":"find_node"}\n\n'
    const { events } = parseSseChunk(text)
    expect(events.map((e) => e.data.node)).toEqual(['intent_node', 'find_node'])
  })

  it('holds back an incomplete trailing event as remainder', () => {
    const text = 'event: node\ndata: {"node":"intent_node"}\n\nevent: node\ndata: {"nod'
    const { events, remainder } = parseSseChunk(text)
    expect(events).toEqual([{ event: 'node', data: { node: 'intent_node' } }])
    expect(remainder).toBe('event: node\ndata: {"nod')
  })

  it('completes a split event when the remainder is prepended to the next chunk', () => {
    const first = parseSseChunk('event: node\ndata: {"nod')
    const second = parseSseChunk(first.remainder + 'e":"intent_node"}\n\n')
    expect(second.events).toEqual([{ event: 'node', data: { node: 'intent_node' } }])
  })
})
