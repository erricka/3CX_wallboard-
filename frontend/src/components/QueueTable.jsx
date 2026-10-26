import { minutesSeconds } from '../format.js'

export default function QueueTable({ queues }) {
  return (
    <div className="table-wrap">
      <table className="board">
        <thead>
          <tr>
            <th className="name-col">Queue</th>
            <th>Agents<br />in work</th>
            <th>Agents<br />free</th>
            <th>Agents<br />talk</th>
            <th>Calls<br />waiting in queue</th>
            <th>Max<br />wait time</th>
            <th>Answered<br />calls</th>
            <th>Missed<br />calls</th>
          </tr>
        </thead>
        <tbody>
          {queues.map((q) => (
            <tr key={q.number}>
              <td className="name-col">{q.name}</td>
              <td>{q.agents_in_work}</td>
              <td>{q.agents_free}</td>
              <td>{q.agents_talk}</td>
              <td className={q.calls_waiting > 0 ? 'alert' : undefined}>{q.calls_waiting}</td>
              <td>{minutesSeconds(q.max_wait_seconds)}</td>
              <td>{q.answered}</td>
              <td>{q.missed}</td>
            </tr>
          ))}
          {queues.length === 0 && (
            <tr><td className="empty" colSpan={8}>No queues found</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
