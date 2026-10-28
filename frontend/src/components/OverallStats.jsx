import { hoursMinutes, percent, waitTime } from '../format.js'

// "00h 27m" with small unit letters, so it stays on one line in a tile
function talkTotal(seconds) {
  const [h, m] = hoursMinutes(seconds).match(/\d+/g)
  return (
    <>
      {h}<small>h</small> {m}<small>m</small>
    </>
  )
}

// Every call on the PBX today, three per row: headline, call directions, inbound service, talk time.
// [snapshot field, label, tile colour, formatter, long value: shrinks with the tile so it always fits]
const TILES = [
  ['total_calls', 'Total Calls', 'total'],
  ['calls_now', 'Calls in Progress', 'talk'],
  ['answer_rate', 'Answer Rate', 'plain', percent],
  ['inbound', 'Inbound Calls', 'plain'],
  ['outbound', 'Outbound Calls', 'plain'],
  ['internal', 'Internal Calls', 'plain'],
  ['inbound_answered', 'Inbound Answered', 'free'],
  ['inbound_missed', 'Inbound Missed', 'waiting'],
  ['avg_wait_seconds', 'Avg Wait Time', 'plain', waitTime],
  ['avg_talk_seconds', 'Avg Talk Time', 'plain', waitTime],
  ['total_talk_seconds', 'Total Talk Time', 'plain', talkTotal, true],
  ['outbound_answered', 'Outbound Answered', 'plain'],
]

export default function OverallStats({ overall }) {
  if (!overall) return null
  return (
    <dl className="overall-tiles">
      {TILES.map(([key, label, tone, format, long]) => (
        <div key={key} className={`tile tile-${tone}${long ? ' tile-long' : ''}`}>
          <dt>{label}</dt>
          <dd>{format ? format(overall[key]) : overall[key]}</dd>
          {key === 'answer_rate' && (
            <span className="rate-bar" aria-hidden="true">
              <i style={{ width: `${overall.answer_rate ?? 0}%` }} />
            </span>
          )}
        </div>
      ))}
    </dl>
  )
}
