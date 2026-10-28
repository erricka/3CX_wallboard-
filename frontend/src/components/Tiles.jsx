// A grid of number tiles. tiles: [snapshot field, label, tile colour, formatter, long value]; an answer rate
// tile also gets a bar. A long value ("60h 00m") shrinks with the tile so it always fits.
export default function Tiles({ tiles, data, className }) {
  return (
    <dl className={className}>
      {tiles.map(([key, label, tone, format, long]) => (
        <div key={key} className={`tile tile-${tone}${long ? ' tile-long' : ''}`}>
          <dt>{label}</dt>
          <dd>{format ? format(data[key]) : data[key]}</dd>
          {key === 'answer_rate' && (
            <span className="rate-bar" aria-hidden="true">
              <i style={{ width: `${data.answer_rate ?? 0}%` }} />
            </span>
          )}
        </div>
      ))}
    </dl>
  )
}
