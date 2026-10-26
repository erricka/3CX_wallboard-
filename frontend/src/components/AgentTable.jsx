import { hoursMinutes } from '../format.js'

const COUNTS = ['inbound', 'outbound', 'missed', 'unanswered_slow']

export default function AgentTable({ agents, slowSeconds }) {
  const totals = Object.fromEntries(
    [...COUNTS, 'work_seconds'].map((key) => [key, agents.reduce((sum, a) => sum + (a[key] || 0), 0)]),
  )

  return (
    <div className="table-wrap">
      <table className="agents">
        <thead>
          <tr>
            <th className="col-agent">Agent</th>
            <th className="col-status">Status</th>
            <th>Inbound calls</th>
            <th>Outbound calls</th>
            <th>Missed calls</th>
            <th>Unanswered within {slowSeconds} sec</th>
            <th>Work time</th>
          </tr>
        </thead>
        <tbody>
          {agents.map((a) => (
            <tr key={a.extension} className={a.kind === 'logoff' ? 'is-off' : undefined}>
              <td className="col-agent">
                <span className="agent-name">{a.name}</span>
                <span className="agent-ext">{a.extension}</span>
              </td>
              <td className="col-status">
                <span className={`pill pill-${a.kind}`}>
                  <i className="dot" />
                  {a.status}
                </span>
              </td>
              <td>{a.inbound}</td>
              <td>{a.outbound}</td>
              <td className={a.missed > 0 ? 'is-bad' : undefined}>{a.missed}</td>
              <td className={a.unanswered_slow > 0 ? 'is-warn' : undefined}>{a.unanswered_slow}</td>
              <td>{hoursMinutes(a.work_seconds)}</td>
            </tr>
          ))}
          {agents.length === 0 && (
            <tr><td className="empty" colSpan={7}>No agents found on the PBX.</td></tr>
          )}
        </tbody>
        {agents.length > 0 && (
          <tfoot>
            <tr>
              <th className="col-agent" scope="row">Total</th>
              <td className="col-status" />
              {COUNTS.map((key) => <td key={key}>{totals[key]}</td>)}
              <td>{hoursMinutes(totals.work_seconds)}</td>
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  )
}
