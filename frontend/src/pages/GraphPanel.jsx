import './GraphPanel.css'

function statusFor(path, nodeName) {
  const entry = path.find((p) => p.node === nodeName)
  return entry ? entry.status : 'pending'
}

export default function GraphPanel({ path }) {
  return (
    <div className="graph-panel">
      <div className="graph-row">
        <div className={`graph-node ${statusFor(path, 'intent_node')}`}>intent_node</div>
      </div>
      <div className="graph-row graph-row-fork">
        <div className={`graph-node ${statusFor(path, 'find_node')}`}>find_node</div>
        <div className={`graph-node ${statusFor(path, 'enrich_node')}`}>enrich_node</div>
      </div>
      <div className="graph-row">
        <div className={`graph-node ${statusFor(path, 'human_gate')}`}>human_gate</div>
      </div>
      <div className="graph-row">
        <div className={`graph-node ${statusFor(path, 'apollo_phone_node')}`}>apollo_phone_node</div>
      </div>
    </div>
  )
}
