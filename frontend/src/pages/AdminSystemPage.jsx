// Admin: pipeline health (every job-collection run), the AI model versions in use, and the audit log
// of every admin decision.
import { Fragment, useEffect, useState } from 'react'
import AdminTabs from '../components/AdminTabs'
import { api } from '../lib/api'

const n = (v) => (v ?? 0).toLocaleString('en-IN')
const when = (iso) => (iso ? new Date(iso).toLocaleString('en-IN',
  { day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit' }) : '-')
const minutes = (a, b) => (a && b ? `${Math.max(1, Math.round((new Date(b) - new Date(a)) / 60000))} min` : '-')
const STATUS_TONE = { success: 'bg-green-50 text-green-800', running: 'bg-amber-50 text-amber-900' }

const ACTIONS = {
  approve_employer: 'Approved recruiter', reject_employer: 'Rejected recruiter', block_employer: 'Blocked recruiter',
  approve_submission: 'Approved job post', reject_submission: 'Rejected job post',
  approve_job_link: 'Published shared link', reject_job_link: 'Rejected shared link',
  report_close_job: 'Took down a reported job', report_dismiss: 'Dismissed a report',
  block_user: 'Blocked account', unblock_user: 'Unblocked account',
  add_company: 'Added company', update_company: 'Changed company',
}

function detailText(details) {
  const parts = []
  if (details.name) parts.push(details.name)
  if (details.reason) parts.push(`reason: ${details.reason}`)
  if (details.note) parts.push(`note: ${details.note}`)
  if (details.jobs_closed) parts.push(`${details.jobs_closed} jobs closed`)
  if (details.spam_score != null) parts.push(`spam score ${Math.round(details.spam_score)}`)
  return parts.join(' \u00b7 ')
}

function Runs({ runs }) {
  const [open, setOpen] = useState(null)
  if (runs.length === 0) return <p className="text-sm text-gray-600">No pipeline runs yet.</p>
  return (
    <div className="bg-white border border-gray-200 rounded overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-gray-600 border-b border-gray-200">
            <th className="px-4 py-2 font-medium">Run</th>
            <th className="px-4 py-2 font-medium">Started</th>
            <th className="px-4 py-2 font-medium">Status</th>
            <th className="px-4 py-2 font-medium text-right">Collected</th>
            <th className="px-4 py-2 font-medium text-right">Kolkata</th>
            <th className="px-4 py-2 font-medium text-right">New</th>
            <th className="px-4 py-2 font-medium text-right">Updated</th>
            <th className="px-4 py-2 font-medium text-right">Closed</th>
            <th className="px-4 py-2"><span className="sr-only">Sources</span></th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <Fragment key={r.id}>
              <tr className="border-b border-gray-100">
                <td className="px-4 py-2">#{r.id} <span className="text-xs text-gray-500">{r.trigger_type}</span></td>
                <td className="px-4 py-2 text-gray-600 whitespace-nowrap">{when(r.started_at)}
                  <span className="text-xs"> ({minutes(r.started_at, r.finished_at)})</span></td>
                <td className="px-4 py-2">
                  <span className={`px-2 py-0.5 rounded-sm font-medium ${STATUS_TONE[r.status] || 'bg-red-50 text-sindoor'}`}>{r.status}</span>
                </td>
                <td className="px-4 py-2 text-right tabular-nums">{n(r.total_collected)}</td>
                <td className="px-4 py-2 text-right tabular-nums">{n(r.kolkata_count)}</td>
                <td className="px-4 py-2 text-right tabular-nums">{n(r.jobs_new)}</td>
                <td className="px-4 py-2 text-right tabular-nums">{n(r.jobs_updated)}</td>
                <td className="px-4 py-2 text-right tabular-nums">{n(r.jobs_closed)}</td>
                <td className="px-4 py-2 text-right">
                  <button onClick={() => setOpen(open === r.id ? null : r.id)} className="text-dusk underline whitespace-nowrap">
                    {open === r.id ? 'Hide' : 'Sources'}
                  </button>
                </td>
              </tr>
              {open === r.id && (
                <tr className="border-b border-gray-100 bg-paper">
                  <td colSpan={9} className="px-4 py-3">
                    {r.error_message && <p className="mb-2 text-sindoor">{r.error_message}</p>}
                    <ul className="grid sm:grid-cols-2 gap-x-6 gap-y-1">
                      {Object.entries(r.source_stats || {}).map(([scope, s]) => (
                        <li key={scope} className="flex justify-between gap-3">
                          <span className="truncate">{scope}</span>
                          <span className={s.ok ? 'text-gray-700' : 'text-sindoor'}>
                            {s.ok ? `${n(s.jobs)} jobs, ${n(s.requests)} calls` : `failed: ${s.error || 'unknown'}`}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function AdminSystemPage() {
  const [runs, setRuns] = useState(null)
  const [models, setModels] = useState(null)
  const [actions, setActions] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([api('/api/admin/pipeline-runs'), api('/api/admin/models'), api('/api/admin/actions', { params: { limit: 100 } })])
      .then(([r, m, a]) => { setRuns(r); setModels(m); setActions(a) })
      .catch((err) => setError(err.message))
  }, [])

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <AdminTabs />
      {error && <p className="p-4 rounded bg-red-50 text-sindoor text-sm">{error}</p>}
      {!runs && !error && <p className="text-gray-500">Loading</p>}

      {runs && (
        <div className="space-y-8">
          <section>
            <h2 className="font-display text-2xl mb-1">Pipeline runs</h2>
            <p className="text-sm text-gray-600 mb-3">The latest 20 job-collection runs. Click Sources to see each source's result.</p>
            <Runs runs={runs} />
          </section>

          <section>
            <h2 className="font-display text-2xl mb-3">AI models in use</h2>
            {models.length === 0 ? <p className="text-sm text-gray-600">No model versions recorded yet.</p> : (
              <ul className="bg-white border border-gray-200 rounded divide-y divide-gray-200 text-sm">
                {models.map((m) => (
                  <li key={`${m.model_name}-${m.version}`} className="px-4 py-3 flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p className="font-medium">{m.model_name} <span className="text-gray-600">{m.version}</span></p>
                      {m.notes && <p className="text-xs text-gray-500">{m.notes}</p>}
                    </div>
                    <span className={m.is_active ? 'text-green-700 font-medium' : 'text-gray-500'}>{m.is_active ? 'Active' : 'Old version'}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h2 className="font-display text-2xl mb-1">Audit log</h2>
            <p className="text-sm text-gray-600 mb-3">Every admin decision, newest first.</p>
            {actions.length === 0 ? <p className="text-sm text-gray-600">No admin actions yet.</p> : (
              <ul className="bg-white border border-gray-200 rounded divide-y divide-gray-200 text-sm">
                {actions.map((a) => (
                  <li key={a.id} className="px-4 py-2.5 grid sm:grid-cols-[11rem_1fr] gap-x-4">
                    <span className="text-gray-500 whitespace-nowrap">{when(a.created_at)}</span>
                    <span>
                      <span className="font-medium">{ACTIONS[a.action] || a.action}</span>
                      <span className="text-gray-600"> by {a.admin_email || 'an admin'}</span>
                      {detailText(a.details) && <span className="block text-xs text-gray-500 break-all">{detailText(a.details)}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
