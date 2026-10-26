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

function QueueCard({ queue: q, showKind }) {
  return (
    <article className="queue-card">
      <header className="queue-head">
        <h3>{q.name}</h3>
        <span className="queue-number">
          {showKind && q.kind === 'ring_group' && <span className="queue-kind">Ring group</span>}
          {q.number}
        </span>
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
  // Label ring groups only when they are shown next to queues.
  const mixed = new Set(queues.map((q) => q.kind)).size > 1
  // Three or more cards: tiles four across so every card fits beside the agents. One card: bigger tiles.
  return (
    <div className={`queue-grid${queues.length >= 3 ? ' is-compact' : ''}${queues.length === 1 ? ' is-single' : ''}`}>
      {queues.map((q) => <QueueCard key={q.number} queue={q} showKind={mixed} />)}
    </div>
  )
}
