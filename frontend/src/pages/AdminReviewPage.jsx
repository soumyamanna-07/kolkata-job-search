// Admin: approve or reject recruiters (company details) and their job posts.
// Riskiest job posts come first (automatic spam score). Every decision is saved in the audit log.
import { useCallback, useEffect, useState } from 'react'
import AdminTabs from '../components/AdminTabs'
import Modal from '../components/Modal'
import { api } from '../lib/api'
import { experienceText, JOB_TYPE_LABELS, postedText, salaryText, WORK_MODE_LABELS } from '../lib/format'
import { useToast } from '../lib/toast'

// the spam check's reason codes, in plain words
const REASON_TEXT = {
  asks_for_fee: 'Asks candidates to pay a fee or deposit',
  easy_money_promise: 'Promises easy money (earn per day / per hour)',
  link_shortener: 'Apply link is a short link (bit.ly and similar)',
  apply_link_on_other_site: "Apply link is not on the company's website or a known job board",
  free_email_domain: 'Recruiter uses a free email (Gmail, Yahoo ...)',
  chat_app_contact: 'Asks candidates to contact on WhatsApp or Telegram',
  unrealistic_salary: 'Very high salary for a fresher',
  very_short_description: 'Very short description',
  shouting_text: 'Lots of CAPITAL LETTERS or !!',
}

function risk(score) {
  if (score == null) return ['not checked', 'bg-gray-100 text-gray-700']
  if (score >= 60) return [`high risk ${Math.round(score)}`, 'bg-red-50 text-sindoor']
  if (score >= 30) return [`some risk ${Math.round(score)}`, 'bg-amber-50 text-amber-900']
  return [`low risk ${Math.round(score)}`, 'bg-green-50 text-green-800']
}

// asks for the reason (the recruiter sees it) before a reject or block
function ReasonBox({ what, onCancel, onSend }) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  return (
    <Modal title={what.title} onClose={onCancel}>
      <form onSubmit={async (e) => { e.preventDefault(); setBusy(true); await onSend(reason.trim()); setBusy(false) }}>
        <label className="block text-sm">Reason (the recruiter sees this)
          <textarea required minLength={3} maxLength={500} rows={3} value={reason} onChange={(e) => setReason(e.target.value)}
                    placeholder={what.placeholder} className="mt-1 w-full rounded border border-gray-300 px-3 py-2" />
        </label>
        {what.warning && <p className="mt-2 text-sm text-sindoor">{what.warning}</p>}
        <div className="mt-4 flex gap-2">
          <button disabled={busy || reason.trim().length < 3}
                  className="px-4 py-2 rounded bg-sindoor text-white font-semibold disabled:opacity-50">{busy ? 'Saving' : what.button}</button>
          <button type="button" onClick={onCancel} className="px-4 py-2 rounded border border-gray-300">Cancel</button>
        </div>
      </form>
    </Modal>
  )
}

function Employer({ e, onDecide }) {
  return (
    <li className="p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-semibold text-lg">{e.company_name}</p>
          <p className="text-sm text-gray-600">
            {e.account_kind === 'agency' ? 'Recruitment agency' : 'Company HR'} {'\u00b7'} sent {postedText(e.updated_at)?.toLowerCase()}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-sm">
          <button onClick={() => onDecide(e, 'approve')} className="px-3 py-1.5 rounded bg-hooghly text-white font-semibold">Approve</button>
          <button onClick={() => onDecide(e, 'reject')} className="px-3 py-1.5 rounded border border-gray-300 hover:bg-red-50">Reject</button>
          <button onClick={() => onDecide(e, 'block')} className="px-3 py-1.5 rounded border border-gray-300 hover:bg-red-50 hover:text-sindoor">Block</button>
        </div>
      </div>
      <dl className="mt-3 grid sm:grid-cols-2 gap-x-6 gap-y-1 text-sm">
        <div className="flex gap-2"><dt className="text-gray-600">Official email</dt><dd className="break-all">{e.official_email}</dd></div>
        <div className="flex gap-2"><dt className="text-gray-600">Logs in as</dt><dd className="break-all">{e.login_email || '-'}</dd></div>
        <div className="flex gap-2"><dt className="text-gray-600">Website</dt><dd className="break-all">
          {e.website ? <a href={e.website} target="_blank" rel="noopener noreferrer" className="text-dusk underline">{e.website}</a> : '-'}
        </dd></div>
        <div className="flex gap-2"><dt className="text-gray-600">GSTIN / CIN</dt><dd>{e.gst_or_cin || '-'}</dd></div>
      </dl>
      <p className="mt-2 text-xs text-gray-500">Check: does the website open, and does the email domain match it?</p>
    </li>
  )
}

function Submission({ s, onDecide }) {
  const [open, setOpen] = useState(false)
  const [label, tone] = risk(s.spam_score)
  const facts = [s.area, salaryText({ ...s, salary_period: 'year' }), experienceText(s),
    JOB_TYPE_LABELS[s.job_type], WORK_MODE_LABELS[s.work_mode]].filter(Boolean)
  return (
    <li className="p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-semibold text-lg">{s.title}</p>
          <p className="text-sm text-gray-600">
            {s.hiring_for ? `${s.hiring_for} via ${s.company_name}` : s.company_name} {'\u00b7'} sent {postedText(s.created_at)?.toLowerCase()}
          </p>
          <p className="mt-1 text-sm text-gray-700">{facts.join(' \u00b7 ')}</p>
        </div>
        <span className={`shrink-0 px-2 py-0.5 rounded-sm text-sm font-medium ${tone}`}>{label}</span>
      </div>
      {s.spam_reasons.length > 0 && (
        <ul className="mt-2 text-sm list-disc pl-5 text-amber-900">
          {s.spam_reasons.map((r) => <li key={r}>{REASON_TEXT[r] || r}</li>)}
        </ul>
      )}
      {s.employer_status !== 'approved' && (
        <p className="mt-2 text-sm p-2 rounded bg-amber-50 text-amber-900">This recruiter is not approved yet. Approve them first.</p>
      )}
      <button onClick={() => setOpen(!open)} className="mt-2 text-sm text-dusk underline">
        {open ? 'Hide the full post' : 'Read the full post'}
      </button>
      {open && (
        <div className="mt-2 p-3 rounded bg-paper text-sm space-y-2">
          <p className="whitespace-pre-line">{s.description}</p>
          {s.skills.length > 0 && <p><span className="text-gray-600">Skills:</span> {s.skills.join(', ')}</p>}
          {s.location && <p><span className="text-gray-600">Address:</span> {s.location}</p>}
          <p className="break-all"><span className="text-gray-600">Apply link:</span>{' '}
            <a href={s.apply_url} target="_blank" rel="noopener noreferrer" className="text-dusk underline">{s.apply_url}</a></p>
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-2 text-sm">
        <button onClick={() => onDecide(s, 'approve')} disabled={s.employer_status !== 'approved'}
                className="px-3 py-1.5 rounded bg-hooghly text-white font-semibold disabled:opacity-40">Approve and publish</button>
        <button onClick={() => onDecide(s, 'reject')} className="px-3 py-1.5 rounded border border-gray-300 hover:bg-red-50">Reject</button>
      </div>
    </li>
  )
}

export default function AdminReviewPage() {
  const toast = useToast()
  const [employers, setEmployers] = useState(null)
  const [posts, setPosts] = useState(null)
  const [error, setError] = useState('')
  const [asking, setAsking] = useState(null)     // { kind, item, decision } waiting for a reason

  const load = useCallback(() => {
    Promise.all([api('/api/admin/employers'), api('/api/admin/submissions')])
      .then(([e, s]) => { setEmployers(e); setPosts(s) })
      .catch((err) => setError(err.message))
  }, [])
  useEffect(() => { load() }, [load])

  async function decide(kind, item, decision, reason = null) {
    const url = kind === 'employer' ? `/api/admin/employers/${item.user_id}/review` : `/api/admin/submissions/${item.id}/review`
    try {
      await api(url, { method: 'POST', body: { decision, reason } })
      const name = kind === 'employer' ? item.company_name : `"${item.title}"`
      toast({ approve: kind === 'employer' ? `${name} approved.` : `${name} is now live.`,
        reject: `${name} rejected.`, block: `${name} blocked. Their live jobs were taken down.` }[decision])
      setAsking(null)
      load()
    } catch (err) {
      toast(err.message)
    }
  }

  const ask = (kind) => (item, decision) => {
    if (decision === 'approve') decide(kind, item, decision)
    else setAsking({ kind, item, decision })
  }

  const what = asking && {
    title: asking.decision === 'block' ? `Block ${asking.item.company_name}?`
      : asking.kind === 'employer' ? `Reject ${asking.item.company_name}?` : `Reject "${asking.item.title}"?`,
    button: asking.decision === 'block' ? 'Block recruiter' : 'Reject',
    placeholder: asking.kind === 'employer' ? 'e.g. The website does not open. Please check it.'
      : 'e.g. The apply link asks candidates to pay a fee.',
    warning: asking.decision === 'block' ? 'Blocking also takes down all their live jobs and stops new posts.' : null,
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <AdminTabs />
      {error && <p className="p-4 rounded bg-red-50 text-sindoor text-sm">{error}</p>}
      {!posts && !error && <p className="text-gray-500">Loading</p>}

      {employers && posts && (
        <div className="space-y-8">
          <section>
            <h2 className="font-display text-2xl mb-3">Recruiters waiting ({employers.length})</h2>
            {employers.length === 0 ? <p className="text-sm text-gray-600">No recruiters waiting.</p> : (
              <ul className="bg-white border border-gray-200 rounded divide-y divide-gray-200">
                {employers.map((e) => <Employer key={e.user_id} e={e} onDecide={ask('employer')} />)}
              </ul>
            )}
          </section>
          <section>
            <h2 className="font-display text-2xl mb-1">Job posts waiting ({posts.length})</h2>
            <p className="text-sm text-gray-600 mb-3">Riskiest first. Approving publishes the job on the site at once.</p>
            {posts.length === 0 ? <p className="text-sm text-gray-600">No job posts waiting.</p> : (
              <ul className="bg-white border border-gray-200 rounded divide-y divide-gray-200">
                {posts.map((s) => <Submission key={s.id} s={s} onDecide={ask('submission')} />)}
              </ul>
            )}
          </section>
        </div>
      )}

      {asking && <ReasonBox what={what} onCancel={() => setAsking(null)}
                            onSend={(reason) => decide(asking.kind, asking.item, asking.decision, reason)} />}
    </div>
  )
}
