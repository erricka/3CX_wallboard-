import { useEffect, useState } from 'react'
import AgentTable from './components/AgentTable.jsx'
import OverallStats from './components/OverallStats.jsx'
import QueueCards from './components/QueueCards.jsx'
import ReportDownload from './components/ReportDownload.jsx'
import logo from './brand/amk-logo-white.svg'
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
  const timeZone = snapshot?.timezone

  return (
    <div className="page">
      <header className="topbar">
        <div className="brand">
          <img className="brand-logo" src={logo} alt="AMK" />
          <h1>Call Center Wallboard</h1>
          {snapshot && !live && (
            <span className="conn conn-down">
              <i className="dot" />
              Reconnecting
            </span>
          )}
        </div>
        <div className="clock">
          <span className="clock-time">{now.toLocaleTimeString(undefined, { timeZone })}</span>
          <span className="clock-date">
            {now.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone })}
          </span>
        </div>
        <ReportDownload />
      </header>

      <main className="content">
        {snapshot?.errors?.map((msg) => <div className="banner" role="status" key={msg}>{msg}</div>)}

        {snapshot ? (
          <>
            <div className="board">
              <div className="board-queues">
                <section aria-labelledby="overall-title">
                  <div className="section-head">
                    <h2 id="overall-title">Overall</h2>
                    <span className="section-meta">All calls on the phone system, today since 00:00</span>
                  </div>
                  <OverallStats overall={snapshot.overall} />
                </section>

                <section aria-labelledby="queues-title">
                  <div className="section-head">
                    <h2 id="queues-title">Queues</h2>
                    <span className="section-meta">Today since 00:00</span>
                  </div>
                  <QueueCards queues={snapshot.queues} />
                </section>
              </div>

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
              {clockTime(snapshot.stats_synced_at, timeZone)} · last update {clockTime(snapshot.generated_at, timeZone)}
            </footer>
          </>
        ) : (
          <div className="waiting">Connecting to 3CX…</div>
        )}
      </main>
    </div>
  )
}
