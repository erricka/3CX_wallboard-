import { percent, waitTime } from '../format.js'
import Tiles from './Tiles.jsx'

// [snapshot field, label, tile colour, formatter]
const TILES = [
  ['agents_in_work', 'Agents in Work', 'work'],
  ['agents_free', 'Agents Free', 'free'],
  ['agents_talk', 'Agents Talking', 'talk'],
  ['calls_waiting', 'Calls Waiting', 'waiting'],
  ['max_wait_seconds', 'Max Wait Time', 'plain', waitTime],
  ['answered', 'Answered Calls', 'plain'],
  ['missed', 'Missed Calls', 'plain'],
  ['answer_rate', 'Answer Rate', 'plain', percent],
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
      <Tiles tiles={TILES} data={q} className="queue-tiles" />
    </article>
  )
}

export default function QueueCards({ queues }) {
  if (queues.length === 0) return <p className="empty">No queues found on the PBX.</p>
  // Label ring groups only when they are shown next to queues.
  const mixed = new Set(queues.map((q) => q.kind)).size > 1
  return (
    <div className="queue-grid">
      {queues.map((q) => <QueueCard key={q.number} queue={q} showKind={mixed} />)}
    </div>
  )
}
