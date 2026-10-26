import { useEffect, useState } from 'react'
import AgentTable from './components/AgentTable.jsx'
import QueueCards from './components/QueueCards.jsx'
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
  const agents = snapshot?.agents ?? []
  const loggedIn = agents.filter((a) => a.logged_in).length

  return (
    <div className="page">
      <header className="topbar">
        <div className="brand">
          <h1>3CX Wallboard</h1>
          {snapshot && !live && (
            <span className="conn conn-down">
              <i className="dot" />
              Reconnecting
            </span>
          )}
        </div>
        <div className="clock">
          <span className="clock-time">{now.toLocaleTimeString()}</span>
          <span className="clock-date">
            {now.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
          </span>
        </div>
        <ReportDownload />
      </header>

      <main className="content">
        {snapshot?.errors?.map((msg) => <div className="banner" role="status" key={msg}>{msg}</div>)}

        {snapshot ? (
          <>
            <div className="board">
              <section className="board-queues" aria-labelledby="queues-title">
                <div className="section-head">
                  <h2 id="queues-title">Queues</h2>
                  <span className="section-meta">Today since 00:00</span>
                </div>
                <QueueCards queues={snapshot.queues} />
              </section>

              <section className="board-agents" aria-labelledby="agents-title">
                <div className="section-head">
                  <h2 id="agents-title">Agents</h2>
                  <span className="section-meta">{loggedIn} of {agents.length} logged in</span>
                </div>
                <AgentTable agents={agents} slowSeconds={snapshot.slow_answer_seconds ?? 5} />
              </section>
            </div>

            <footer className="footnote">
              Status updates every 3 seconds · daily counters since 00:00 ({snapshot.timezone}), refreshed{' '}
              {clockTime(snapshot.stats_synced_at)} · last update {clockTime(snapshot.generated_at)}
            </footer>
          </>
        ) : (
          <div className="waiting">Connecting to 3CX…</div>
        )}
      </main>
    </div>
  )
}
