// Saved jobs and the jobs you clicked Apply on.
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import JobCard from '../components/JobCard'
import { api } from '../lib/api'
import { useSaved } from '../lib/saved'

const TABS = [['saved', 'Saved jobs', '/api/me/saved-jobs'], ['applied', 'Applied', '/api/me/applied']]

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
            : 'Jobs you open with the Apply button will be listed here, so you can keep track.'}
        </div>
      )}
      {jobs && jobs.length > 0 && (
        <div className="mt-6 bg-white border border-gray-200 rounded divide-y divide-gray-200">
          {jobs.map((job) => (
            <JobCard key={job.id} job={job}
              extra={job.status !== 'open' && <p className="mt-2 text-sm text-amber-800">This job has closed.</p>}
              badge={<span className="text-xs text-gray-500 whitespace-nowrap pt-1.5">
                {tab === 'saved' ? 'Saved' : 'Applied'} {new Date(job.saved_at).toLocaleDateString('en-IN')}
              </span>} />
          ))}
        </div>
      )}
    </div>
  )
}
