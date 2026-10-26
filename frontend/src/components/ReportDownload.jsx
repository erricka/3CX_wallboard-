import { useState } from 'react'
import { API_URL } from '../api.js'

const PERIODS = [
  ['today', 'Today'],
  ['yesterday', 'Yesterday'],
  ['7days', 'Last 7 days'],
  ['1month', 'Last 1 month'],
]

export default function ReportDownload() {
  const [period, setPeriod] = useState('today')
  const [format, setFormat] = useState('xlsx')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function download() {
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/reports/daily?period=${period}&format=${format}`)
      if (!res.ok) throw new Error(`Report failed (HTTP ${res.status})`)
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
        <button type="button" onClick={download} disabled={busy}>{busy ? 'Preparing…' : 'Download'}</button>
      </div>
      {error && <p className="report-error" role="alert">{error}</p>}
    </div>
  )
}
