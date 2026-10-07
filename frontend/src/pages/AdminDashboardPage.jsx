// Admin: the numbers that matter at a glance, and what is waiting for a decision.
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import AdminTabs from '../components/AdminTabs'
import { api } from '../lib/api'
import { SOURCE_CREDITS } from '../lib/format'

const n = (v) => (v ?? 0).toLocaleString('en-IN')
const SOURCE_NAMES = { employer: 'Recruiter posts', greenhouse: 'Greenhouse', lever: 'Lever', ashby: 'Ashby',
  workable: 'Workable', career_page: 'Career pages', campus: 'Campus links', community: 'Shared links' }
const sourceName = (s) => SOURCE_CREDITS[s]?.name || SOURCE_NAMES[s] || s

function when(iso) {
  return iso ? new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) : '-'
}

function Waiting({ value, label, to }) {
  const busy = value > 0
  return (
    <Link to={to} className={`block rounded border p-4 hover:border-dusk ${busy ? 'bg-amber-50 border-amber-300' : 'bg-white border-gray-200'}`}>
      <p className="font-display text-3xl tabular-nums">{n(value)}</p>
      <p className="text-sm text-gray-700">{label}</p>
      <p className="mt-1 text-xs text-gray-500">{busy ? 'Review now' : 'Nothing waiting'}</p>
    </Link>
  )
}

export default function AdminDashboardPage() {
  const [stats, setStats] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => { api('/api/admin/stats').then(setStats).catch((e) => setError(e.message)) }, [])

  const sources = stats ? Object.entries(stats.open_jobs_by_source) : []
  const maxSource = Math.max(1, ...sources.map(([, c]) => c))
  const run = stats?.last_pipeline_run

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <AdminTabs />
      {error && <p className="p-4 rounded bg-red-50 text-sindoor text-sm">{error}</p>}
      {!stats && !error && <p className="text-gray-500">Loading</p>}

      {stats && (
        <div className="space-y-6">
          <section>
            <h2 className="font-display text-2xl mb-3">Waiting for you</h2>
            <div className="grid sm:grid-cols-3 gap-4">
              <Waiting value={stats.pending_employers} label="recruiters to approve" to="/admin/review" />
              <Waiting value={stats.pending_job_posts} label="job posts to approve" to="/admin/review" />
              <Waiting value={stats.open_reports} label="jobs reported by users" to="/admin/reports" />
            </div>
          </section>

          <div className="grid grid-cols-2 md:grid-cols-4 bg-white border border-gray-200 rounded divide-x divide-y md:divide-y-0 divide-gray-200">
            {[[n(stats.open_jobs), 'open jobs'], [n(stats.new_jobs_7_days), 'new jobs, last 7 days'],
              [n(Object.values(stats.users_by_role).reduce((a, b) => a + b, 0)), 'accounts'],
              [n(stats.saved_cvs), 'saved CVs']].map(([v, l]) => (
              <div key={l} className="px-4 py-3">
                <p className="font-display text-2xl tabular-nums">{v}</p>
                <p className="text-xs text-gray-600">{l}</p>
              </div>
            ))}
          </div>

          <div className="grid md:grid-cols-2 gap-5 items-start">
            <section className="bg-white border border-gray-200 rounded p-5">
              <h2 className="font-display text-xl">Open jobs by source</h2>
              <ul className="mt-3 space-y-2">
                {sources.map(([source, count]) => (
                  <li key={source} className="grid grid-cols-[8rem_1fr_3.5rem] items-center gap-3 text-sm">
                    <span className="truncate">{sourceName(source)}</span>
                    <span className="h-3 bg-paper rounded-r">
                      <span className="bar block h-3 rounded-r" style={{ width: `${(count / maxSource) * 100}%` }} />
                    </span>
                    <span className="tabular-nums text-right text-gray-700">{n(count)}</span>
                  </li>
                ))}
              </ul>
              {stats.jobs_without_embedding > 0 && (
                <p className="mt-3 text-sm p-2 rounded bg-amber-50 text-amber-900">
                  {n(stats.jobs_without_embedding)} open jobs have no AI embedding yet. Run the embed step.
                </p>
              )}
            </section>

            <section className="bg-white border border-gray-200 rounded p-5">
              <h2 className="font-display text-xl">Last pipeline run</h2>
              {!run ? <p className="mt-2 text-sm text-gray-600">No runs yet.</p> : (
                <div className="mt-2 text-sm space-y-2">
                  <p>
                    <span className={`px-2 py-0.5 rounded-sm font-medium ${run.status === 'success' ? 'bg-green-50 text-green-800'
                      : run.status === 'running' ? 'bg-amber-50 text-amber-900' : 'bg-red-50 text-sindoor'}`}>{run.status}</span>
                    <span className="ml-2 text-gray-600">#{run.id}, started {when(run.started_at)} ({run.trigger_type})</span>
                  </p>
                  <p className="text-gray-700">
                    Collected {n(run.total_collected)}, Kolkata {n(run.kolkata_count)}, unique {n(run.unique_count)}.
                    New {n(run.jobs_new)}, updated {n(run.jobs_updated)}, closed {n(run.jobs_closed)}.
                  </p>
                  {run.error_message && <p className="text-sindoor">{run.error_message}</p>}
                </div>
              )}
              <h3 className="mt-4 font-semibold text-sm">Accounts by type</h3>
              <p className="text-sm text-gray-700">
                {['candidate', 'employer', 'admin'].map((r) => `${n(stats.users_by_role[r])} ${r === 'employer' ? 'recruiter' : r}s`).join(', ')}
                {stats.blocked_users > 0 && `, ${n(stats.blocked_users)} blocked`}
              </p>
            </section>
          </div>
        </div>
      )}
    </div>
  )
}
