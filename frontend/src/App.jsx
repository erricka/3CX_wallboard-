import { useEffect, useState } from 'react'
import AgentTable from './components/AgentTable.jsx'
import QueueTable from './components/QueueTable.jsx'
import ReportDownload from './components/ReportDownload.jsx'
import { clockTime } from './format.js'
import { useWallboard } from './useWallboard.js'

function useClock() {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  return now
}

export default function App() {
  const { snapshot, connected } = useWallboard()
  const now = useClock()
  const live = connected && snapshot && !snapshot.stale

  return (
    <div className="page">
      <header className="topbar">
        <div className="title">
          <h1>3CX Wallboard</h1>
          <span className={`conn ${live ? 'conn-live' : 'conn-down'}`}>{live ? 'Live' : 'Reconnecting…'}</span>
          <span className="meta">Updated {clockTime(snapshot?.generated_at)}</span>
        </div>
        <div className="clock">{now.toLocaleTimeString()}</div>
        <ReportDownload />
      </header>

      {snapshot?.errors?.map((msg) => <div className="banner" key={msg}>{msg}</div>)}

      {snapshot ? (
        <main>
          <QueueTable queues={snapshot.queues} />
          <AgentTable agents={snapshot.agents} slowSeconds={snapshot.slow_answer_seconds ?? 5} />
          <footer className="meta">
            Daily counters since 00:00 ({snapshot.timezone}) · refreshed {clockTime(snapshot.stats_synced_at)}
          </footer>
        </main>
      ) : (
        <div className="waiting">Connecting to 3CX…</div>
      )}
    </div>
  )
}
