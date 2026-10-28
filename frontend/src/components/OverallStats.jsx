import { hoursMinutes, percent, waitTime } from '../format.js'
import Tiles from './Tiles.jsx'

// "00h 27m" with small unit letters, so it stays on one line in a tile
function talkTotal(seconds) {
  const [h, m] = hoursMinutes(seconds).match(/\d+/g)
  return (
    <>
      {h}<small>h</small> {m}<small>m</small>
    </>
  )
}

// Every call on the PBX today. [snapshot field, label, tile colour, formatter], four per row.
const TILES = [
  ['total_calls', 'Total Calls', 'total'],
  ['inbound', 'Inbound Calls', 'plain'],
  ['outbound', 'Outbound Calls', 'plain'],
  ['internal', 'Internal Calls', 'plain'],
  ['inbound_answered', 'Inbound Answered', 'free'],
  ['inbound_missed', 'Inbound Missed', 'waiting'],
  ['answer_rate', 'Answer Rate', 'plain', percent],
  ['avg_wait_seconds', 'Avg Wait Time', 'plain', waitTime],
  ['avg_talk_seconds', 'Avg Talk Time', 'plain', waitTime],
  ['total_talk_seconds', 'Total Talk Time', 'plain', talkTotal, true],
  ['outbound_answered', 'Outbound Answered', 'plain'],
  ['calls_now', 'Calls in Progress', 'talk'],
]

export default function OverallStats({ overall }) {
  return overall ? <Tiles tiles={TILES} data={overall} className="overall-tiles" /> : null
}
