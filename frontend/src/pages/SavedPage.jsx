// My jobs: saved jobs, and My applications (the jobs you applied to, with the stage you are at).
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import JobCard from '../components/JobCard'
import { api } from '../lib/api'
import { useSaved } from '../lib/saved'
import { useToast } from '../lib/toast'

const TABS = [['saved', 'Saved jobs', '/api/me/saved-jobs'], ['applications', 'My applications', '/api/me/applications']]

// the stages of an application, in order
const STAGES = [
  ['applied', 'Applied'],
  ['interview', 'Interview'],
  ['offer', 'Offer'],
  ['rejected', 'Rejected'],
  ['no_reply', 'No reply'],
]
const STAGE_COLORS = {
  applied: 'bg-dusk/10 text-dusk',
  interview: 'bg-amber-100 text-amber-900',
  offer: 'bg-green-100 text-green-800',
  rejected: 'bg-gray-100 text-gray-600',
  no_reply: 'bg-gray-100 text-gray-600',
}

function dateText(value) {
  return new Date(value).toLocaleDateString('en-IN')
}

function ApplicationTracker({ job, onChange }) {
  const toast = useToast()
  const [note, setNote] = useState(job.note || '')

  function save(changes, message) {
    api(`/api/me/applications/${job.id}`, { method: 'PATCH', body: changes })
      .then((updated) => {
        onChange(updated)
        if (message) toast(message)
      })
      .catch((e) => toast(e.message))
  }

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
      <label className="sr-only" htmlFor={`stage-${job.id}`}>Stage</label>
      <select id={`stage-${job.id}`} value={job.application_status}
              onChange={(e) => save({ status: e.target.value }, 'Stage updated')}
              className={`rounded px-2 py-1 font-medium border border-gray-200 ${STAGE_COLORS[job.application_status]}`}>
        {STAGES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
      <label className="sr-only" htmlFor={`note-${job.id}`}>Private note</label>
      <input id={`note-${job.id}`} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)}
             onBlur={() => { if (note.trim() !== (job.note || '')) save({ note }, 'Note saved') }}
             placeholder="Private note, e.g. interview on Monday"
             className="flex-1 min-w-48 rounded border border-gray-300 px-2 py-1 focus:outline-none focus:ring-2 focus:ring-dusk" />
      {job.status !== 'open' && <span className="text-amber-800">This job has closed.</span>}
    </div>
  )
}

function StageSummary({ jobs }) {
  const counts = STAGES.map(([value, label]) => [label, jobs.filter((j) => j.application_status === value).length])
    .filter(([, n]) => n > 0)
  return (
    <p className="mt-4 flex flex-wrap gap-2 text-sm">
      {counts.map(([label, n]) => (
        <span key={label} className="px-2.5 py-1 rounded-full bg-white border border-gray-200">
          {label}: <strong>{n}</strong>
        </span>
      ))}
    </p>
  )
}

export default function SavedPage() {
  const [tab, setTab] = useState('saved')
  const [jobs, setJobs] = useState(null)
  const [error, setError] = useState('')
  const { count } = useSaved()

  useEffect(() => {
    setJobs(null)
    setError('')
    api(TABS.find((t) => t[0] === tab)[2]).then(setJobs).catch((e) => setError(e.message))
  }, [tab, count])

  const replace = (updated) => setJobs((list) => list.map((j) => (j.id === updated.id ? updated : j)))

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <h1 className="font-display text-4xl">My jobs</h1>
      <div className="mt-5 flex gap-1 border-b border-gray-200" role="tablist">
        {TABS.map(([key, label]) => (
          <button key={key} role="tab" aria-selected={tab === key} onClick={() => setTab(key)}
                  className={`px-4 py-2 -mb-px border-b-2 text-sm font-medium ${tab === key
                    ? 'border-sindoor text-ink' : 'border-transparent text-gray-500 hover:text-ink'}`}>
            {label}
          </button>
        ))}
      </div>

      {error && <p className="mt-6 p-4 rounded bg-red-50 text-sindoor text-sm">{error}</p>}
      {jobs && jobs.length === 0 && (
        <div className="mt-6 p-8 bg-white border border-gray-200 rounded text-gray-700">
          {tab === 'saved'
            ? <>No saved jobs yet. Press the bookmark on any job to keep it here. <Link to="/" className="text-dusk underline">Browse jobs</Link></>
            : <>No applications yet. When you press Apply on a job, it is added here so you can track each stage: applied, interview, offer. <Link to="/" className="text-dusk underline">Browse jobs</Link></>}
        </div>
      )}
      {tab === 'applications' && jobs && jobs.length > 0 && <StageSummary jobs={jobs} />}
      {jobs && jobs.length > 0 && (
        <div className="mt-6 bg-white border border-gray-200 rounded divide-y divide-gray-200">
          {jobs.map((job) => (
            <JobCard key={job.id} job={job}
              extra={tab === 'applications'
                ? <ApplicationTracker job={job} onChange={replace} />
                : job.status !== 'open' && <p className="mt-2 text-sm text-amber-800">This job has closed.</p>}
              badge={<span className="text-xs text-gray-500 whitespace-nowrap pt-1.5">
                {tab === 'saved' ? `Saved ${dateText(job.saved_at)}` : `Applied ${dateText(job.applied_at)}`}
              </span>} />
          ))}
        </div>
      )}
    </div>
  )
}
