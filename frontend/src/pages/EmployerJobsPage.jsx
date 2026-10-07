// Recruiter: all job posts with their review status, and how each live job is doing
// (shown in results, views, apply clicks, saves). Edit posts waiting for review; close any post.
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import EmployerTabs from '../components/EmployerTabs'
import Modal from '../components/Modal'
import { api } from '../lib/api'
import { postedText } from '../lib/format'
import Icon from '../lib/icons'
import { useToast } from '../lib/toast'

const BADGE = {
  pending: ['Waiting for review', 'bg-amber-50 text-amber-900'],
  live: ['Live', 'bg-green-50 text-green-800'],
  expired: ['Closed (over 30 days or link not working)', 'bg-gray-100 text-gray-700'],
  rejected: ['Not approved', 'bg-red-50 text-sindoor'],
  closed: ['Closed by you', 'bg-gray-100 text-gray-700'],
}

function badgeKey(post, stats) {
  if (post.status !== 'approved') return post.status
  return stats?.job_status === 'open' ? 'live' : 'expired'
}

const count = (n) => (n ?? 0).toLocaleString('en-IN')

function Totals({ totals }) {
  const items = [
    [count(totals.posts), 'job posts'],
    [count(totals.live_jobs), 'live now'],
    [count(totals.shown_in_results), 'times shown in results'],
    [count(totals.views), 'job page views'],
    [count(totals.apply_clicks), 'apply clicks'],
    [totals.apply_rate == null ? '-' : `${totals.apply_rate}%`, 'of views clicked Apply'],
  ]
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 bg-white border border-gray-200 rounded divide-x divide-y lg:divide-y-0 divide-gray-200">
      {items.map(([value, label]) => (
        <div key={label} className="px-4 py-3">
          <p className="font-display text-2xl tabular-nums">{value}</p>
          <p className="text-xs text-gray-600">{label}</p>
        </div>
      ))}
    </div>
  )
}

function PostRow({ post, stats, onClose }) {
  const key = badgeKey(post, stats)
  const [label, tone] = BADGE[key] || [post.status, '']
  const canEdit = post.status === 'pending' || post.status === 'rejected'
  const canClose = post.status === 'pending' || (post.status === 'approved' && stats?.job_status === 'open')
  return (
    <li className="p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-semibold text-lg leading-snug">{post.title}</p>
          <p className="mt-0.5 text-sm text-gray-600">
            {[post.hiring_for, post.area, `posted ${postedText(post.created_at)?.toLowerCase()}`].filter(Boolean).join(' \u00b7 ')}
          </p>
        </div>
        <span className={`shrink-0 px-2 py-0.5 rounded-sm text-sm font-medium ${tone}`}>{label}</span>
      </div>

      {post.rejection_reason && (
        <p className="mt-2 text-sm p-2 rounded bg-red-50">
          <span className="font-medium">Admin's reason:</span> {post.rejection_reason}
        </p>
      )}

      {post.status === 'approved' && stats && (
        <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
          {[['Shown in results', stats.shown_in_results], ['Views', stats.views], ['Apply clicks', stats.apply_clicks],
            ['Saves', stats.saves], ['Views, last 7 days', stats.views_7_days]].map(([name, value]) => (
            <div key={name} className="flex gap-1.5">
              <dt className="text-gray-600">{name}</dt>
              <dd className="font-semibold tabular-nums">{count(value)}</dd>
            </div>
          ))}
          {stats.apply_rate != null && (
            <div className="flex gap-1.5"><dt className="text-gray-600">Apply rate</dt>
              <dd className="font-semibold tabular-nums">{stats.apply_rate}%</dd></div>
          )}
        </dl>
      )}

      <div className="mt-3 flex flex-wrap gap-2 text-sm">
        {key === 'live' && (
          <Link to={`/jobs/${stats.job_id}`} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded border border-gray-300 hover:border-dusk">
            <Icon name="external" className="w-4 h-4" /> See it on the site
          </Link>
        )}
        {canEdit && (
          <Link to={`/employer/jobs/${post.id}/edit`} className="px-3 py-1.5 rounded border border-gray-300 hover:border-dusk">
            {post.status === 'rejected' ? 'Correct and send again' : 'Edit'}
          </Link>
        )}
        {canClose && (
          <button onClick={() => onClose(post)} className="px-3 py-1.5 rounded border border-gray-300 hover:bg-red-50 hover:text-sindoor">
            {post.status === 'pending' ? 'Withdraw' : 'Close job (position filled)'}
          </button>
        )}
      </div>
    </li>
  )
}

export default function EmployerJobsPage() {
  const toast = useToast()
  const [posts, setPosts] = useState(null)
  const [stats, setStats] = useState(null)
  const [error, setError] = useState('')
  const [closing, setClosing] = useState(null)       // the post the "are you sure?" box is about
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    Promise.all([api('/api/employer/jobs'), api('/api/employer/stats')])
      .then(([p, s]) => { setPosts(p); setStats(s) })
      .catch((err) => setError(err.status === 403 ? 'Add your company details and get them approved first.' : err.message))
  }, [])
  useEffect(() => { load() }, [load])

  async function confirmClose() {
    setBusy(true)
    try {
      await api(`/api/employer/jobs/${closing.id}/close`, { method: 'POST' })
      toast(closing.status === 'pending' ? 'Post withdrawn.' : 'Job closed. It no longer shows on the site.')
      setClosing(null)
      load()
    } catch (err) {
      toast(err.message)
    }
    setBusy(false)
  }

  const statsById = Object.fromEntries((stats?.jobs || []).map((s) => [s.submission_id, s]))

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <EmployerTabs />
      {error && <p className="p-4 rounded bg-red-50 text-sindoor text-sm">{error}</p>}
      {!posts && !error && <p className="text-gray-500">Loading your jobs</p>}

      {posts && posts.length === 0 && (
        <div className="bg-white border border-gray-200 rounded p-6 text-center">
          <p className="font-display text-2xl">No job posts yet</p>
          <p className="mt-1 text-gray-600">Post your first job. It goes live after a quick review.</p>
          <Link to="/employer/post" className="inline-block mt-4 px-5 py-2 rounded bg-taxi text-ink font-semibold hover:bg-taxi-deep">
            Post a job
          </Link>
        </div>
      )}

      {posts && posts.length > 0 && (
        <div className="space-y-5">
          <Totals totals={stats.totals} />
          <p className="text-xs text-gray-500">
            Counts come from job seekers on this site. Your own visits to your jobs are not counted.
          </p>
          <ul className="bg-white border border-gray-200 rounded divide-y divide-gray-200">
            {posts.map((post) => <PostRow key={post.id} post={post} stats={statsById[post.id]} onClose={setClosing} />)}
          </ul>
        </div>
      )}

      {closing && (
        <Modal title={closing.status === 'pending' ? 'Withdraw this post?' : 'Close this job?'} onClose={() => setClosing(null)}>
          <p className="text-sm text-gray-600">
            "{closing.title}" will {closing.status === 'pending' ? 'not be reviewed or published' : 'be taken off the site at once'}.
            This cannot be undone, but you can always post the job again.
          </p>
          <div className="mt-4 flex gap-2">
            <button onClick={confirmClose} disabled={busy}
                    className="px-4 py-2 rounded bg-sindoor text-white font-semibold disabled:opacity-50">
              {busy ? 'Closing' : closing.status === 'pending' ? 'Withdraw' : 'Close job'}
            </button>
            <button onClick={() => setClosing(null)} className="px-4 py-2 rounded border border-gray-300">Keep it</button>
          </div>
        </Modal>
      )}
    </div>
  )
}
