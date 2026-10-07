// Admin: "Update jobs now". Collects from every source, closes old jobs and creates the AI embeddings,
// so new jobs show up for users straight away (search, Best for You, Ask AI). One update at a time.
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import Icon from '../lib/icons'
import { useToast } from '../lib/toast'

const MODES = [
  ['quick', 'Quick update', 'New Adzuna jobs and Jooble, about 3 minutes'],
  ['full', 'Full update', 'All Adzuna jobs (closes removed ones) and Jooble, about 8 minutes'],
]

function minutesSince(iso) {
  const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  return m < 1 ? 'less than a minute' : `${m} minute${m === 1 ? '' : 's'}`
}

export default function JobUpdatePanel({ onFinished }) {
  const toast = useToast()
  const [state, setState] = useState(null)
  const [error, setError] = useState('')
  const [showLog, setShowLog] = useState(false)
  const wasRunning = useRef(false)

  const load = useCallback(() => api('/api/admin/job-update').then(setState).catch((e) => setError(e.message)), [])
  useEffect(() => { load() }, [load])

  const busy = state?.running || state?.other_run_active
  // while an update runs, check on it every 3 seconds
  useEffect(() => {
    if (!busy) return undefined
    const timer = setInterval(load, 3000)
    return () => clearInterval(timer)
  }, [busy, load])

  // tell the page when an update has just finished, so it can show the new numbers
  useEffect(() => {
    if (!state) return
    if (wasRunning.current && !state.running) {
      toast(state.exit_code === 0 ? 'Jobs updated. Users see the new jobs now.' : 'The update finished with problems. See the log.')
      onFinished?.()
    }
    wasRunning.current = state.running
  }, [state, toast, onFinished])

  async function start(mode) {
    setError('')
    try {
      setState(await api('/api/admin/job-update', { method: 'POST', body: { mode } }))
      setShowLog(true)
    } catch (err) {
      setError(err.message)
    }
  }

  const finished = state && !state.running && state.finished_at
  return (
    <section className="bg-white border border-gray-200 rounded overflow-hidden">
      <div className="laal-paar" />
      <div className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="font-display text-2xl">Update jobs now</h2>
            <p className="text-sm text-gray-600 max-w-xl">
              Collects from every source, closes old jobs and prepares new ones for AI matching. Users see the new
              jobs as soon as it finishes. Once the site is online it will also run by itself twice a day.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {MODES.map(([mode, label, hint]) => (
              <button key={mode} onClick={() => start(mode)} disabled={!state || busy} title={hint}
                      className={`inline-flex items-center gap-2 px-4 py-2 rounded font-semibold text-sm disabled:opacity-50 ${
                        mode === 'quick' ? 'bg-taxi text-ink hover:bg-taxi-deep' : 'border border-gray-300 hover:border-dusk'}`}>
                <Icon name="clock" className="w-4 h-4" /> {label}
              </button>
            ))}
          </div>
        </div>
        <p className="mt-2 text-xs text-gray-500">{MODES.map(([, label, hint]) => `${label}: ${hint}.`).join(' ')}</p>

        {error && <p className="mt-3 p-3 rounded bg-red-50 text-sindoor text-sm">{error}</p>}

        {state?.running && (
          <p className="mt-3 p-3 rounded bg-amber-50 text-amber-900 text-sm" role="status">
            <span className="font-semibold">Updating ({state.mode === 'full' ? 'full' : 'quick'})...</span> started {minutesSince(state.started_at)} ago.
            You can leave this page; the update keeps going.
          </p>
        )}
        {state?.other_run_active && (
          <p className="mt-3 p-3 rounded bg-amber-50 text-amber-900 text-sm" role="status">
            A scheduled update is running right now. The buttons come back when it finishes.
          </p>
        )}
        {finished && (
          <p className={`mt-3 p-3 rounded text-sm ${state.exit_code === 0 ? 'bg-green-50 text-green-800' : 'bg-red-50 text-sindoor'}`}>
            {state.exit_code === 0
              ? `Last update (${state.mode}) finished ${minutesSince(state.finished_at)} ago. New jobs are live for users.`
              : `Last update (${state.mode}) finished with problems (code ${state.exit_code}). Check the log and the pipeline runs.`}
          </p>
        )}

        {state?.log_tail?.length > 0 && (
          <div className="mt-3">
            <button onClick={() => setShowLog(!showLog)} className="text-sm text-dusk underline">
              {showLog ? 'Hide the log' : 'Show the log'}
            </button>
            {showLog && (
              <pre className="mt-2 p-3 rounded bg-paper text-xs leading-relaxed overflow-x-auto max-h-64">
                {state.log_tail.join('\n')}
              </pre>
            )}
          </div>
        )}
      </div>
    </section>
  )
}
