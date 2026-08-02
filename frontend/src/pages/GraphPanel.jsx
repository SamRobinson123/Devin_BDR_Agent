import './GraphPanel.css'

function statusFor(path, nodeName) {
  const entry = path.find((p) => p.node === nodeName)
  return entry ? entry.status : 'pending'
}

function Node({ path, name }) {
  return <div className={`graph-node ${statusFor(path, name)}`}>{name}</div>
}

export default function GraphPanel({ path }) {
  return (
    <div className="graph-panel">
      <div className="graph-row">
        <Node path={path} name="intent_node" />
      </div>
      <div className="graph-row graph-row-fork">
        <Node path={path} name="find_node" />
        <Node path={path} name="enrich_node" />
      </div>
      <div className="graph-row">
        <Node path={path} name="dedupe_node" />
      </div>
      <div className="graph-row">
        <Node path={path} name="research_node" />
      </div>
      <div className="graph-row">
        <Node path={path} name="score_node" />
      </div>
      <div className="graph-row">
        <Node path={path} name="human_gate" />
      </div>
      <div className="graph-row">
        <Node path={path} name="apollo_phone_node" />
      </div>
      <div className="graph-row">
        <Node path={path} name="draft_node" />
      </div>
    </div>
  )
}
