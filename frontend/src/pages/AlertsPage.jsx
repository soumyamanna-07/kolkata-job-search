// My job alerts: see, pause, restart and delete. New alerts are made from a search ("Email me new jobs").
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { JOB_TYPE_LABELS, WORK_MODE_LABELS } from '../lib/format'
import Icon from '../lib/icons'
import { useToast } from '../lib/toast'

function describe(f) {
  const parts = []
  if (f.q) parts.push(`"${f.q}"`)
  if (f.areas?.length) parts.push(f.areas.join(', '))
  if (f.skills?.length) parts.push(`skills: ${f.skills.join(', ')}`)
  if (f.job_types?.length) parts.push(f.job_types.map((t) => JOB_TYPE_LABELS[t]).join(', '))
  if (f.work_modes?.length) parts.push(f.work_modes.map((m) => WORK_MODE_LABELS[m]).join(', '))
  if (f.experience_years != null) parts.push(`${f.experience_years} years experience`)
  if (f.salary_expected) parts.push(`${(f.salary_expected / 100000).toFixed(1)} LPA or more`)
  return parts.join('; ') || 'Jobs matching your CV'
}

export default function AlertsPage() {
  const [alerts, setAlerts] = useState(null)
  const [error, setError] = useState('')
  const toast = useToast()

  const load = () => api('/api/me/alerts').then(setAlerts).catch((e) => setError(e.message))
  useEffect(() => { load() }, [])

  async function toggle(alert) {
    const { name, filters, use_cv_match, frequency } = alert
    try {
      await api(`/api/me/alerts/${alert.id}`, {
        method: 'PUT', body: { name, filters, use_cv_match, frequency, is_active: !alert.is_active } })
      toast(alert.is_active ? 'Alert paused' : 'Alert turned on')
      load()
    } catch (e) {
      toast(e.message)
    }
  }

  async function remove(alert) {
    try {
      await api(`/api/me/alerts/${alert.id}`, { method: 'DELETE' })
      toast('Alert deleted')
      load()
    } catch (e) {
      toast(e.message)
    }
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <h1 className="font-display text-4xl">Job alerts</h1>
      <p className="mt-1 text-gray-600">
        We email you new jobs for each alert. To add one, search for jobs and press "Email me new jobs".
      </p>

      {error && <p className="mt-6 p-4 rounded bg-red-50 text-sindoor text-sm">{error}</p>}
      {alerts && alerts.length === 0 && (
        <div className="mt-6 p-8 bg-white border border-gray-200 rounded text-gray-700">
          No alerts yet. <Link to="/" className="text-dusk underline">Search for jobs</Link> and press
          "Email me new jobs" above the results.
        </div>
      )}
      {alerts && alerts.length > 0 && (
        <ul className="mt-6 bg-white border border-gray-200 rounded divide-y divide-gray-200">
          {alerts.map((a) => (
            <li key={a.id} className="p-5 flex flex-wrap items-start gap-4">
              <span className={`inline-flex w-10 h-10 rounded items-center justify-center ${a.is_active ? 'bg-dusk text-taxi' : 'bg-gray-100 text-gray-400'}`}>
                <Icon name="bell" />
              </span>
              <div className="flex-1 min-w-0">
                <p className="font-display text-lg">{a.name}</p>
                <p className="text-sm text-gray-600">{describe(a.filters)}</p>
                <p className="text-xs text-gray-500 mt-1">
                  {a.frequency === 'daily' ? 'Every day' : 'Once a week'}
                  {a.is_active ? '' : ', paused'}
                  {a.last_sent_at && `, last email ${new Date(a.last_sent_at).toLocaleDateString('en-IN')}`}
                </p>
              </div>
              <div className="flex gap-2">
                <button onClick={() => toggle(a)} className="px-3 py-1.5 rounded border border-gray-300 text-sm hover:bg-paper">
                  {a.is_active ? 'Pause' : 'Turn on'}
                </button>
                <button onClick={() => remove(a)} className="px-3 py-1.5 rounded border border-gray-300 text-sm text-sindoor hover:bg-red-50">
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
