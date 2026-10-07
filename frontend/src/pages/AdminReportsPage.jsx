// Admin: jobs that users reported (fake, closed, wrong details ...) and job links shared by
// students and college placement officers (TPOs). Every decision is saved in the audit log.
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import AdminTabs from '../components/AdminTabs'
import Modal from '../components/Modal'
import { api } from '../lib/api'
import { JOB_TYPE_LABELS, postedText, SOURCE_CREDITS, WORK_MODE_LABELS } from '../lib/format'
import { useToast } from '../lib/toast'

const REPORT_REASONS = {
  spam: 'Spam', fake: 'Fake or a scam', already_closed: 'Job already closed', wrong_location: 'Not in Kolkata',
  wrong_details: 'Wrong details', other: 'Other',
}
const AREAS = ['Kolkata', 'Salt Lake', 'New Town', 'Howrah']
const input = 'mt-1 w-full rounded border border-gray-300 px-3 py-2'
const lakhToRupees = (v) => (v === '' ? null : Math.round(parseFloat(v) * 100000))
const years = (v) => (v === '' ? null : parseFloat(v))

// ---------------------------------------------------------------- reported jobs
function Report({ r, onAct }) {
  return (
    <li className="p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Link to={`/jobs/${r.job_id}`} className="font-semibold text-lg hover:underline">{r.job_title}</Link>
          <p className="text-sm text-gray-600">
            {r.company_name} {'\u00b7'} from {SOURCE_CREDITS[r.job_source]?.name || r.job_source}
            {' \u00b7 '}job is {r.job_status} {'\u00b7'} reported {postedText(r.created_at)?.toLowerCase()}
          </p>
        </div>
        {r.reports_for_job > 1 && (
          <span className="shrink-0 px-2 py-0.5 rounded-sm text-sm font-medium bg-red-50 text-sindoor">
            {r.reports_for_job} reports on this job
          </span>
        )}
      </div>
      <p className="mt-2 text-sm">
        <span className="font-medium">{REPORT_REASONS[r.reason] || r.reason}</span>
        {r.details && <span className="text-gray-700">: {r.details}</span>}
      </p>
      <p className="mt-1 text-sm break-all">
        <a href={r.apply_url} target="_blank" rel="noopener noreferrer" className="text-dusk underline">Open the apply link</a>
        <span className="text-gray-500"> to check it</span>
      </p>
      <div className="mt-3 flex flex-wrap gap-2 text-sm">
        {r.job_status === 'open' && (
          <button onClick={() => onAct(r, 'close_job')} className="px-3 py-1.5 rounded bg-sindoor text-white font-semibold">
            Take the job down
          </button>
        )}
        <button onClick={() => onAct(r, 'dismiss')} className="px-3 py-1.5 rounded border border-gray-300 hover:border-dusk">
          Dismiss (the job is fine)
        </button>
      </div>
    </li>
  )
}

// ---------------------------------------------------------------- shared links
function SharedLink({ l, onDone }) {
  const toast = useToast()
  const [mode, setMode] = useState(null)          // null, 'approve' or 'reject'
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [reason, setReason] = useState('')
  const [form, setForm] = useState({ title: l.title || '', company_name: l.company_name || '', description: '',
    area: 'Kolkata', job_type: '', work_mode: '', salary_min: '', salary_max: '', experience_min: '', experience_max: '' })
  const update = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  async function send(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    const body = mode === 'reject' ? { decision: 'reject', reason: reason.trim() } : {
      decision: 'approve', title: form.title.trim(), company_name: form.company_name.trim(),
      description: form.description.trim(), area: form.area, job_type: form.job_type || null,
      work_mode: form.work_mode || null, salary_min: lakhToRupees(form.salary_min), salary_max: lakhToRupees(form.salary_max),
      experience_min: years(form.experience_min), experience_max: years(form.experience_max),
    }
    try {
      await api(`/api/admin/job-links/${l.id}/review`, { method: 'POST', body })
      toast(mode === 'reject' ? 'Link rejected.' : `"${body.title}" is now live.`)
      onDone()
    } catch (err) {
      setError(err.message)
    }
    setBusy(false)
  }

  return (
    <li className="p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-semibold text-lg">{l.title || l.company_name || 'Job link'}</p>
          <p className="text-sm text-gray-600">
            {l.submitter_type === 'tpo' ? 'College placement officer (TPO)' : 'Student or job seeker'}
            {l.submitted_by_email ? ` (${l.submitted_by_email})` : ''} {'\u00b7'} {postedText(l.created_at)?.toLowerCase()}
          </p>
        </div>
      </div>
      <p className="mt-2 text-sm break-all">
        <a href={l.url} target="_blank" rel="noopener noreferrer" className="text-dusk underline">{l.url}</a>
      </p>
      {l.note && <p className="mt-1 text-sm text-gray-700">Note: {l.note}</p>}

      {!mode && (
        <div className="mt-3 flex flex-wrap gap-2 text-sm">
          <button onClick={() => setMode('approve')} className="px-3 py-1.5 rounded bg-hooghly text-white font-semibold">
            Fill in details and publish
          </button>
          <button onClick={() => setMode('reject')} className="px-3 py-1.5 rounded border border-gray-300 hover:bg-red-50">Reject</button>
        </div>
      )}

      {mode && (
        <form onSubmit={send} className="mt-3 p-4 rounded bg-paper space-y-3 text-sm">
          {mode === 'reject' ? (
            <label className="block">Reason (the person who shared it sees this)
              <textarea required minLength={3} maxLength={500} rows={2} value={reason} onChange={(e) => setReason(e.target.value)}
                        placeholder="e.g. This job is in Pune, not Kolkata." className={input} />
            </label>
          ) : (
            <>
              <p className="text-gray-600">Open the link, then copy the details from the job page.</p>
              <div className="grid sm:grid-cols-2 gap-3">
                <label className="block">Job title
                  <input required minLength={3} maxLength={120} value={form.title} onChange={update('title')} className={input} />
                </label>
                <label className="block">Company
                  <input required minLength={2} maxLength={120} value={form.company_name} onChange={update('company_name')} className={input} />
                </label>
              </div>
              <label className="block">Description
                <textarea required minLength={30} maxLength={8000} rows={5} value={form.description} onChange={update('description')} className={input} />
              </label>
              <div className="grid sm:grid-cols-3 gap-3">
                <label className="block">Area
                  <select value={form.area} onChange={update('area')} className={input}>
                    {AREAS.map((a) => <option key={a}>{a}</option>)}
                  </select>
                </label>
                <label className="block">Job type
                  <select value={form.job_type} onChange={update('job_type')} className={input}>
                    <option value="">Not stated</option>
                    {Object.entries(JOB_TYPE_LABELS).map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                  </select>
                </label>
                <label className="block">Work mode
                  <select value={form.work_mode} onChange={update('work_mode')} className={input}>
                    <option value="">Not stated</option>
                    {Object.entries(WORK_MODE_LABELS).map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                  </select>
                </label>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <label className="block">Salary from (lakh/yr)
                  <input type="number" min="0" step="0.1" value={form.salary_min} onChange={update('salary_min')} className={input} />
                </label>
                <label className="block">Salary to (lakh/yr)
                  <input type="number" min="0" step="0.1" value={form.salary_max} onChange={update('salary_max')} className={input} />
                </label>
                <label className="block">Experience from (yrs)
                  <input type="number" min="0" max="50" step="0.5" value={form.experience_min} onChange={update('experience_min')} className={input} />
                </label>
                <label className="block">Experience to (yrs)
                  <input type="number" min="0" max="50" step="0.5" value={form.experience_max} onChange={update('experience_max')} className={input} />
                </label>
              </div>
            </>
          )}
          {error && <p className="p-2 rounded bg-red-50 text-sindoor">{error}</p>}
          <div className="flex gap-2">
            <button disabled={busy} className={`px-4 py-2 rounded text-white font-semibold disabled:opacity-50 ${mode === 'reject' ? 'bg-sindoor' : 'bg-hooghly'}`}>
              {busy ? 'Saving' : mode === 'reject' ? 'Reject link' : 'Publish job'}
            </button>
            <button type="button" onClick={() => { setMode(null); setError('') }} className="px-4 py-2 rounded border border-gray-300">Cancel</button>
          </div>
        </form>
      )}
    </li>
  )
}

export default function AdminReportsPage() {
  const toast = useToast()
  const [reports, setReports] = useState(null)
  const [links, setLinks] = useState(null)
  const [error, setError] = useState('')
  const [closing, setClosing] = useState(null)      // report whose job we are about to take down

  const load = useCallback(() => {
    Promise.all([api('/api/admin/reports'), api('/api/admin/job-links')])
      .then(([r, l]) => { setReports(r); setLinks(l) })
      .catch((err) => setError(err.message))
  }, [])
  useEffect(() => { load() }, [load])

  async function act(report, action) {
    try {
      await api(`/api/admin/reports/${report.id}/resolve`, { method: 'POST', body: { action } })
      toast(action === 'close_job' ? 'Job taken down. All its reports are resolved.' : 'Report dismissed.')
      setClosing(null)
      load()
    } catch (err) {
      toast(err.message)
    }
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <AdminTabs />
      {error && <p className="p-4 rounded bg-red-50 text-sindoor text-sm">{error}</p>}
      {!links && !error && <p className="text-gray-500">Loading</p>}

      {reports && links && (
        <div className="space-y-8">
          <section>
            <h2 className="font-display text-2xl mb-1">Reported jobs ({reports.length})</h2>
            <p className="text-sm text-gray-600 mb-3">Jobs with the most reports come first.</p>
            {reports.length === 0 ? <p className="text-sm text-gray-600">No open reports.</p> : (
              <ul className="bg-white border border-gray-200 rounded divide-y divide-gray-200">
                {reports.map((r) => <Report key={r.id} r={r} onAct={(rep, a) => (a === 'close_job' ? setClosing(rep) : act(rep, a))} />)}
              </ul>
            )}
          </section>
          <section>
            <h2 className="font-display text-2xl mb-1">Shared job links ({links.length})</h2>
            <p className="text-sm text-gray-600 mb-3">Links from students and TPOs. Check the page, then publish it as a job.</p>
            {links.length === 0 ? <p className="text-sm text-gray-600">No links waiting.</p> : (
              <ul className="bg-white border border-gray-200 rounded divide-y divide-gray-200">
                {links.map((l) => <SharedLink key={l.id} l={l} onDone={load} />)}
              </ul>
            )}
          </section>
        </div>
      )}

      {closing && (
        <Modal title="Take this job down?" onClose={() => setClosing(null)}>
          <p className="text-sm text-gray-600">
            "{closing.job_title}" at {closing.company_name} will be closed at once, and all open reports on it are resolved.
          </p>
          <div className="mt-4 flex gap-2">
            <button onClick={() => act(closing, 'close_job')} className="px-4 py-2 rounded bg-sindoor text-white font-semibold">Take it down</button>
            <button onClick={() => setClosing(null)} className="px-4 py-2 rounded border border-gray-300">Keep it</button>
          </div>
        </Modal>
      )}
    </div>
  )
}
