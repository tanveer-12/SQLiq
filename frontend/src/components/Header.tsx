import { useState } from 'react'
import { Link } from 'react-router-dom'
import { getApiKey } from '../api'

interface HeaderProps {
  tagline?: string
}

export default function Header({ tagline }: HeaderProps) {
  const [savedKey, setSavedKey] = useState(() => localStorage.getItem('sqliq_api_key') || '')
  const [inputKey, setInputKey]   = useState(savedKey)
  const [keyOpen,  setKeyOpen]    = useState(false)

  const hasCustomKey = !!savedKey
  const dashboardKey = getApiKey()

  function openSettings() {
    setInputKey(savedKey)
    setKeyOpen(true)
  }

  function saveKey() {
    const trimmed = inputKey.trim()
    if (trimmed) {
      localStorage.setItem('sqliq_api_key', trimmed)
    } else {
      localStorage.removeItem('sqliq_api_key')
    }
    setSavedKey(trimmed)
    setKeyOpen(false)
  }

  return (
    <header className="bg-surface border-b border-border sticky top-0 z-10">
      <div className="max-w-6xl mx-auto px-6 py-3.5 flex items-center gap-4">
        <Link to="/" className="text-[18px] font-bold tracking-tight text-text no-underline">
          SQLiq
        </Link>

        {tagline ? (
          <span className="text-muted text-[13px] flex-1">{tagline}</span>
        ) : (
          <span className="flex-1" />
        )}

        {/* API key configurator */}
        <div className="relative">
          <button
            onClick={openSettings}
            title={hasCustomKey ? 'API key set — click to change' : 'Set your API key'}
            className={`text-[12px] px-2.5 py-1 border rounded-md flex items-center gap-1.5 transition-colors ${
              hasCustomKey
                ? 'border-success/40 text-success hover:bg-green-50'
                : 'border-border text-muted hover:bg-code-bg'
            }`}
          >
            <span className="text-[14px]">{hasCustomKey ? '🔑' : '⚙️'}</span>
            <span>API Key</span>
            {hasCustomKey && (
              <span className="w-1.5 h-1.5 rounded-full bg-success inline-block" />
            )}
          </button>

          {keyOpen && (
            <div className="absolute right-0 top-full mt-2 w-80 bg-surface border border-border rounded-[10px] p-4 shadow-xl z-20">
              <p className="text-[13px] font-semibold mb-1">AgentState API Key</p>
              <p className="text-[12px] text-muted mb-3 leading-[1.5]">
                Required for the live trace stream and dashboard. Must match a key in{' '}
                <code className="bg-code-bg px-1 rounded">AGENTSTATE_API_KEYS</code>.
              </p>
              <input
                type="password"
                value={inputKey}
                onChange={e => setInputKey(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && saveKey()}
                placeholder={import.meta.env.VITE_AGENTSTATE_API_KEY || 'dev-key-123'}
                className="font-mono text-[12px] w-full bg-code-bg border border-border rounded-[6px] px-3 py-2 outline-none focus:border-accent mb-3 transition-colors"
                autoFocus
              />
              <div className="flex gap-2">
                <button
                  onClick={saveKey}
                  className="flex-1 bg-accent hover:bg-accent-dark text-white text-[13px] font-medium rounded-[6px] px-3 py-1.5 transition-colors"
                >
                  Save
                </button>
                {savedKey && (
                  <button
                    onClick={() => { localStorage.removeItem('sqliq_api_key'); setSavedKey(''); setInputKey(''); setKeyOpen(false) }}
                    className="text-[13px] text-danger px-3 py-1.5 border border-red-200 rounded-[6px] hover:bg-red-50 transition-colors"
                  >
                    Clear
                  </button>
                )}
                <button
                  onClick={() => setKeyOpen(false)}
                  className="text-[13px] text-muted px-3 py-1.5 border border-border rounded-[6px] hover:bg-code-bg transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>

        <a
          href={`/dashboard?key=${encodeURIComponent(dashboardKey)}`}
          target="_blank"
          rel="noreferrer"
          className="text-[13px] text-accent no-underline px-2.5 py-1 border border-border rounded-md hover:bg-code-bg transition-colors"
        >
          Agent Dashboard ↗
        </a>
      </div>

      {/* Click-outside overlay */}
      {keyOpen && (
        <div className="fixed inset-0 z-10" onClick={() => setKeyOpen(false)} />
      )}
    </header>
  )
}
