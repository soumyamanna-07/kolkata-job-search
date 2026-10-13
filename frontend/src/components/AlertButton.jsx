// "Email me new jobs like these": turns the current search into a daily or weekly job alert.
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import Icon from '../lib/icons'
import { useToast } from '../lib/toast'
import Modal from './Modal'

const list = (value) => (value || '').split(',').map((v) => v.trim()).filter(Boolean)

// URL search params -> the filters our alerts API understands
export function alertFilters(params) {
  const f = {}
  if (params.get('q')) f.q = params.get('q')
  if (params.get('area')) f.areas = list(params.get('area'))
  if (params.get('skills')) f.skills = list(params.get('skills'))
  if (params.get('job_type')) f.job_types = list(params.get('job_type'))
  if (params.get('work_mode')) f.work_modes = list(params.get('work_mode'))
  if (params.get('salary_expected')) f.salary_expected = Number(params.get('salary_expected'))
  if (params.get('experience_years')) f.experience_years = Number(params.get('experience_years'))
  return f
}

function suggestedName(f) {
  const what = f.q || (f.skills && f.skills.join(', ')) || 'New jobs'
  const where = f.areas ? f.areas.join(' / ') : 'Kolkata'
  return `${what} in ${where}`.slice(0, 80)
}

export default function AlertButton({ params }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const toast = useToast()
  const filters = alertFilters(params)
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [frequency, setFrequency] = useState('daily')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const empty = Object.keys(filters).length === 0

  function start() {
    if (!user) {
      toast('Log in to get job alerts by email')
      navigate('/login')
      return
    }
    setName(suggestedName(filters))
    setError('')
    setOpen(true)
  }

  async function save(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api('/api/me/alerts', { method: 'POST', body: { name, filters, frequency } })
      setOpen(false)
      toast('Alert created. New jobs will come to your email.')
    } catch (err) {
      setError(err.message)
    }
    setBusy(false)
  }

  return (
    <>
      <button type="button" onClick={start} disabled={empty}
              title={empty ? 'Search or pick a filter first' : 'Get new jobs for this search by email'}
              className="inline-flex items-center gap-2 px-3 py-1.5 rounded border border-dusk text-dusk text-sm font-medium hover:bg-dusk hover:text-white disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-dusk">
        <Icon name="bell" className="w-4 h-4" /> Email me new jobs
      </button>
      {open && (
        <Modal title="Job alert for this search" onClose={() => setOpen(false)}>
          <form onSubmit={save} className="space-y-3">
            <label className="block text-sm">
              <span className="text-gray-600">Alert name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={80}
                     className="mt-1 w-full rounded border border-gray-300 px-3 py-2" />
            </label>
            <fieldset className="text-sm">
              <legend className="text-gray-600 mb-1">How often</legend>
              {[['daily', 'Every day'], ['weekly', 'Once a week']].map(([v, label]) => (
                <label key={v} className="inline-flex items-center gap-2 mr-5">
                  <input type="radio" name="frequency" checked={frequency === v} onChange={() => setFrequency(v)}
                         className="accent-dusk" /> {label}
                </label>
              ))}
            </fieldset>
            <p className="text-xs text-gray-500">Emails go to {user?.email}. Every email has a link to stop the alert.</p>
            {error && <p className="text-sm text-sindoor">{error}</p>}
            <button disabled={busy} className="w-full py-2 rounded bg-dusk text-white font-medium disabled:opacity-50">
              {busy ? 'Creating' : 'Create alert'}
            </button>
          </form>
        </Modal>
      )}
    </>
  )
}
