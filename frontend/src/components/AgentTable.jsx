import { hoursMinutes } from '../format.js'

export default function AgentTable({ agents, slowSeconds }) {
  return (
    <div className="table-wrap">
      <table className="board">
        <thead>
          <tr>
            <th className="name-col">Agent</th>
            <th>Status</th>
            <th>Inbound<br />calls</th>
            <th>Outbound<br />calls</th>
            <th>Missed<br />calls</th>
            <th>Unanswered<br />within {slowSeconds} sec</th>
            <th>Work time</th>
          </tr>
        </thead>
        <tbody>
          {agents.map((a) => (
            <tr key={a.extension}>
              <td className="name-col" title={`Extension ${a.extension}`}>{a.name}</td>
              <td className={`status status-${a.kind}`}>{a.status}</td>
              <td>{a.inbound}</td>
              <td>{a.outbound}</td>
              <td>{a.missed}</td>
              <td>{a.unanswered_slow}</td>
              <td>{hoursMinutes(a.work_seconds)}</td>
            </tr>
          ))}
          {agents.length === 0 && (
            <tr><td className="empty" colSpan={7}>No agents found</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
