const pad = (n) => String(n).padStart(2, '0')

// 2160 -> "00h 36m"
export function hoursMinutes(seconds) {
  const minutes = Math.floor((seconds || 0) / 60)
  return `${pad(Math.floor(minutes / 60))}h ${pad(minutes % 60)}m`
}

// 42 -> "00m 42s"
export function minutesSeconds(seconds) {
  const s = Math.floor(seconds || 0)
  return `${pad(Math.floor(s / 60))}m ${pad(s % 60)}s`
}

export function clockTime(iso) {
  return iso ? new Date(iso).toLocaleTimeString() : '—'
}
