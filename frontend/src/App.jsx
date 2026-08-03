import { useEffect, useState } from 'react'
import Chat from './pages/Chat'
import LeadsDatabase from './pages/LeadsDatabase'
import Settings from './pages/Settings'
import Usage from './pages/Usage'
import './App.css'

const NAV_ITEMS = [
  { id: 'chat', icon: '💬', label: 'Chat' },
  { id: 'leads', icon: '📇', label: 'Leads Database' },
  { id: 'usage', icon: '📊', label: 'Usage & Spend' },
  { id: 'settings', icon: '⚙️', label: 'Settings' },
]

function initialTheme() {
  const stored = localStorage.getItem('theme')
  if (stored === 'light' || stored === 'dark') return stored
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export default function App() {
  const [tab, setTab] = useState('chat')
  const [theme, setTheme] = useState(initialTheme)
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('sidebar') === 'collapsed')

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('theme', theme)
  }, [theme])

  useEffect(() => {
    localStorage.setItem('sidebar', collapsed ? 'collapsed' : 'expanded')
  }, [collapsed])

  useEffect(() => {
    const open = () => setTab('leads')
    window.addEventListener('open-leads', open)
    return () => window.removeEventListener('open-leads', open)
  }, [])

  return (
    <div className="app-shell" data-collapsed={collapsed}>
      <nav className="app-sidebar">
        <div className="app-sidebar-top">
          <div className="app-sidebar-brand">
            <span className="app-brand-mark" aria-hidden="true">B</span>
            <span className="app-brand-name">BDR Agent</span>
          </div>
          <button
            className="app-icon-button"
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? '»' : '«'}
          </button>
        </div>

        <div className="app-nav">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              className="app-nav-item"
              data-active={tab === item.id}
              aria-current={tab === item.id}
              title={item.label}
              onClick={() => setTab(item.id)}
            >
              <span className="app-nav-icon" aria-hidden="true">{item.icon}</span>
              <span className="app-nav-label">{item.label}</span>
            </button>
          ))}
        </div>

        <button
          className="app-nav-item app-theme-toggle"
          onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          <span className="app-nav-icon" aria-hidden="true">{theme === 'dark' ? '☀️' : '🌙'}</span>
          <span className="app-nav-label">{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>
        </button>
      </nav>
      <div className="app-content">
        <div className="app-pane" hidden={tab !== 'chat'}>
          <Chat />
        </div>
        <div className="app-pane" hidden={tab !== 'leads'}>
          <LeadsDatabase active={tab === 'leads'} />
        </div>
        <div className="app-pane" hidden={tab !== 'usage'}>
          <Usage active={tab === 'usage'} />
        </div>
        <div className="app-pane" hidden={tab !== 'settings'}>
          <Settings active={tab === 'settings'} />
        </div>
      </div>
    </div>
  )
}
