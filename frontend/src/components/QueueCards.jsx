import { waitTime } from '../format.js'

// [snapshot field, label, tile colour, formatter]
const TILES = [
  ['agents_in_work', 'Agents in Work', 'work'],
  ['agents_free', 'Agents Free', 'free'],
  ['agents_talk', 'Agents Talking', 'talk'],
  ['calls_waiting', 'Calls Waiting', 'waiting'],
  ['max_wait_seconds', 'Max Wait Time', 'plain', waitTime],
  ['answered', 'Answered Calls', 'plain'],
  ['missed', 'Missed Calls', 'plain'],
]

function QueueCard({ queue: q }) {
  return (
    <article className="queue-card">
      <header className="queue-head">
        <h3>{q.name}</h3>
        <span className="queue-number">{q.number}</span>
      </header>
      <dl className="queue-tiles">
        {TILES.map(([key, label, tone, format]) => (
          <div key={key} className={`tile tile-${tone}`}>
            <dt>{label}</dt>
            <dd>{format ? format(q[key]) : q[key]}</dd>
          </div>
        ))}
      </dl>
    </article>
  )
}

export default function QueueCards({ queues }) {
  if (queues.length === 0) return <p className="empty">No queues found on the PBX.</p>
  return (
    <div className="queue-grid">
      {queues.map((q) => <QueueCard key={q.number} queue={q} />)}
    </div>
  )
}
