const pad = (n) => String(n).padStart(2, '0')

// 2160 -> "00h 36m"
export function hoursMinutes(seconds) {
  const minutes = Math.floor((seconds || 0) / 60)
  return `${pad(Math.floor(minutes / 60))}h ${pad(minutes % 60)}m`
}

// 155 -> "02:35"
export function waitTime(seconds) {
  const s = Math.floor(seconds || 0)
  return `${pad(Math.floor(s / 60))}:${pad(s % 60)}`
}

// Times are shown in the call centre's timezone (from the server), whatever the PC is set to.
export function clockTime(iso, timeZone) {
  return iso ? new Date(iso).toLocaleTimeString(undefined, { timeZone }) : '—'
}
