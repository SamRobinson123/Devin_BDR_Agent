import './GraphPanel.css'

const NODE_W = 136
const NODE_H = 38

const NODES = [
  { name: 'intent_node', label: 'Understand request', icon: '🧭', x: 170, y: 28 },
  { name: 'find_node', label: 'Web search', icon: '🔎', x: 86, y: 104 },
  { name: 'dedupe_node', label: 'Dedupe', icon: '🧹', x: 86, y: 176 },
  { name: 'research_node', label: 'Company research', icon: '🏢', x: 86, y: 248 },
  { name: 'profile_node', label: 'Person profile', icon: '👤', x: 86, y: 320 },
  { name: 'score_node', label: 'ICP score', icon: '🎯', x: 86, y: 392 },
  { name: 'human_gate', label: 'Your call', icon: '✋', x: 86, y: 464 },
  { name: 'enrich_node', label: 'Find emails', icon: '✉️', x: 170, y: 540 },
  { name: 'phone_node', label: 'Find phones', icon: '📞', x: 170, y: 612 },
  { name: 'draft_node', label: 'Write drafts', icon: '✍️', x: 170, y: 684 },
  { name: 'notify_node', label: 'Notify you', icon: '🔔', x: 170, y: 756 },
]

const EDGES = [
  { from: 'intent_node', to: 'find_node' },
  { from: 'intent_node', to: 'enrich_node', lane: 268 },
  { from: 'find_node', to: 'dedupe_node' },
  { from: 'dedupe_node', to: 'research_node' },
  { from: 'research_node', to: 'profile_node' },
  { from: 'profile_node', to: 'score_node' },
  { from: 'score_node', to: 'human_gate' },
  { from: 'human_gate', to: 'enrich_node' },
  { from: 'enrich_node', to: 'phone_node' },
  { from: 'phone_node', to: 'draft_node' },
  { from: 'draft_node', to: 'notify_node' },
  { from: 'phone_node', to: 'notify_node', lane: 288 },
]

const BY_NAME = Object.fromEntries(NODES.map((n) => [n.name, n]))

function edgePath({ from, to, lane }) {
  const a = BY_NAME[from]
  const b = BY_NAME[to]
  if (lane !== undefined) {
    const side = a.x + NODE_W / 2
    return `M ${side} ${a.y} C ${lane} ${a.y + 24} ${lane} ${b.y - 24} ${b.x + NODE_W / 2} ${b.y}`
  }
  const y1 = a.y + NODE_H / 2
  const y2 = b.y - NODE_H / 2
  const mid = (y1 + y2) / 2
  return `M ${a.x} ${y1} C ${a.x} ${mid} ${b.x} ${mid} ${b.x} ${y2}`
}

function statusFor(path, nodeName) {
  const entry = path.find((p) => p.node === nodeName)
  return entry ? entry.status : 'pending'
}

function edgeStatus(path, edge) {
  const from = statusFor(path, edge.from)
  const to = statusFor(path, edge.to)
  if (from === 'completed' && to === 'completed') return 'completed'
  if (from === 'completed' && to === 'current') return 'active'
  return 'pending'
}

export default function GraphPanel({ path = [] }) {
  return (
    <div className="graph-panel">
      <svg
        className="graph-canvas"
        viewBox={`0 0 340 ${NODES.at(-1).y + 40}`}
        preserveAspectRatio="xMidYMin meet"
        role="img"
        aria-label="Agent run graph"
      >
        {EDGES.map((edge) => {
          const status = edgeStatus(path, edge)
          const id = `edge-${edge.from}-${edge.to}`
          return (
            <g key={id} className={`graph-edge ${status}`}>
              <path id={id} className="graph-edge-line" d={edgePath(edge)} fill="none" />
              {status === 'active' && (
                <>
                  <path className="graph-edge-flow" d={edgePath(edge)} fill="none" />
                  <circle className="graph-edge-dot" r="3.5">
                    <animateMotion dur="1.3s" repeatCount="indefinite">
                      <mpath href={`#${id}`} />
                    </animateMotion>
                  </circle>
                </>
              )}
            </g>
          )
        })}

        {NODES.map((node) => {
          const status = statusFor(path, node.name)
          return (
            <g
              key={node.name}
              className={`graph-node ${status}`}
              data-node={node.name}
              transform={`translate(${node.x - NODE_W / 2} ${node.y - NODE_H / 2})`}
            >
              {status === 'current' && (
                <rect
                  className="graph-node-halo"
                  x="-5"
                  y="-5"
                  width={NODE_W + 10}
                  height={NODE_H + 10}
                  rx="14"
                />
              )}
              <rect className="graph-node-box" width={NODE_W} height={NODE_H} rx="10" />
              <text className="graph-node-icon" x="14" y={NODE_H / 2 + 4}>{node.icon}</text>
              <text className="graph-node-label" x="34" y={NODE_H / 2 + 4}>{node.label}</text>
              {status === 'completed' && (
                <text className="graph-node-check" x={NODE_W - 12} y={NODE_H / 2 + 4}>✓</text>
              )}
            </g>
          )
        })}
      </svg>
    </div>
  )
}
