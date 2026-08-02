export function parseSseChunk(buffer) {
  const events = []
  const blocks = buffer.split('\n\n')
  // The last element is either '' (buffer ended cleanly on a blank line) or an
  // incomplete trailing block — either way, it is not yet a complete event.
  const remainder = blocks.pop()

  for (const block of blocks) {
    if (!block.trim()) continue
    let eventType = null
    let data = null
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) {
        eventType = line.slice('event:'.length).trim()
      } else if (line.startsWith('data:')) {
        data = JSON.parse(line.slice('data:'.length).trim())
      }
    }
    if (eventType) events.push({ event: eventType, data })
  }

  return { events, remainder }
}
