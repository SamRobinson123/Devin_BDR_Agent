import { useState } from 'react'
import Chat from './pages/Chat'
import LeadsDatabase from './pages/LeadsDatabase'
import './App.css'

const NAV_ITEMS = [
  { id: 'chat', icon: '💬', label: 'Chat' },
  { id: 'leads', icon: '📇', label: 'Leads Database' },
]

export default function App() {
  const [tab, setTab] = useState('chat')

  return (
    <div className="app-shell">
      <nav className="app-sidebar">
        <div className="app-sidebar-brand">BDR Agent</div>
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            className="app-nav-item"
            data-active={tab === item.id}
            aria-current={tab === item.id}
            onClick={() => setTab(item.id)}
          >
            <span className="app-nav-icon" aria-hidden="true">{item.icon}</span>
            <span className="app-nav-label">{item.label}</span>
          </button>
        ))}
      </nav>
      <div className="app-content">
        <div style={{ display: tab === 'chat' ? 'contents' : 'none' }}>
          <Chat />
        </div>
        <div style={{ display: tab === 'leads' ? 'contents' : 'none' }}>
          <LeadsDatabase active={tab === 'leads'} />
        </div>
      </div>
    </div>
  )
}
