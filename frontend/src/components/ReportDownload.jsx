import { useState } from 'react'
import { API_URL } from '../api.js'

const PERIODS = [
  ['today', 'Today'],
  ['yesterday', 'Yesterday'],
  ['7days', 'Last 7 days'],
  ['1month', 'Last 1 month'],
  ['range', 'Date Range'],
]

// YYYY-MM-DD in the browser's local time (what <input type="date"> uses)
function isoDate(d) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function daysAgo(n) {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return isoDate(d)
}

function rangeProblem(start, end, today) {
  if (!start || !end) return 'Choose a start date and an end date.'
  if (start > end) return 'The start date must be on or before the end date.'
  if (end > today) return 'The end date cannot be in the future.'
  return null
}

export default function ReportDownload() {
  const today = isoDate(new Date())
  const [period, setPeriod] = useState('today')
  const [format, setFormat] = useState('xlsx')
  const [start, setStart] = useState(() => daysAgo(6))
  const [end, setEnd] = useState(today)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const isRange = period === 'range'
  const problem = isRange ? rangeProblem(start, end, today) : null

  async function download() {
    setBusy(true)
    setError(null)
    try {
      const query = new URLSearchParams({ period, format })
      if (isRange) {
        query.set('start', start)
        query.set('end', end)
      }
      const res = await fetch(`${API_URL}/api/reports/daily?${query}`)
      if (!res.ok) {
        const detail = await res.json().then((body) => body.detail).catch(() => null)
        throw new Error(typeof detail === 'string' ? detail : `Report failed (HTTP ${res.status})`)
      }
      const disposition = res.headers.get('Content-Disposition') || ''
      const filename = /filename="([^"]+)"/.exec(disposition)?.[1] || `3cx-daily-report.${format}`
      const url = URL.createObjectURL(await res.blob())
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="report">
      <span className="report-title">Daily report</span>
      <div className="report-controls">
        <select id="report-period" value={period} onChange={(e) => setPeriod(e.target.value)} disabled={busy}
          aria-label="Report period">
          {PERIODS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <select id="report-format" value={format} onChange={(e) => setFormat(e.target.value)} disabled={busy}
          aria-label="File format">
          <option value="xlsx">Excel</option>
          <option value="csv">CSV</option>
        </select>
        <button type="button" onClick={download} disabled={busy || Boolean(problem)}>
          {busy ? 'Preparing…' : 'Download'}
        </button>
      </div>
      {isRange && (
        <div className="report-range">
          <label htmlFor="report-start">From</label>
          <input id="report-start" type="date" value={start} max={end || today} disabled={busy}
            onChange={(e) => setStart(e.target.value)} />
          <label htmlFor="report-end">To</label>
          <input id="report-end" type="date" value={end} min={start} max={today} disabled={busy}
            onChange={(e) => setEnd(e.target.value)} />
        </div>
      )}
      {busy && isRange && <p className="report-hint">Long ranges can take a minute the first time.</p>}
      {(problem || error) && <p className="report-error" role="alert">{problem || error}</p>}
    </div>
  )
}
