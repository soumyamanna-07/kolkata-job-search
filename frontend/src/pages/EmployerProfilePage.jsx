// Recruiter: company details. An admin approves them before any job can be posted.
import { useEffect, useState } from 'react'
import EmployerTabs from '../components/EmployerTabs'
import { api } from '../lib/api'
import Icon from '../lib/icons'
import { useToast } from '../lib/toast'

const EMPTY = { company_name: '', official_email: '', website: '', gst_or_cin: '', account_kind: 'company' }

export const VERIFICATION = {
  pending: ['Waiting for admin approval', 'bg-amber-50 text-amber-900',
    'An admin checks new company details, usually within a day. You can post jobs once they are approved.'],
  approved: ['Approved', 'bg-green-50 text-green-800', 'Your company is approved. You can post jobs.'],
  rejected: ['Not approved', 'bg-red-50 text-sindoor', 'Please correct the details below and save them again.'],
  blocked: ['Blocked', 'bg-red-50 text-sindoor', 'This recruiter account is blocked and cannot post jobs.'],
}

export default function EmployerProfilePage() {
  const toast = useToast()
  const [saved, setSaved] = useState(null)            // what the server has (null = nothing yet)
  const [form, setForm] = useState(EMPTY)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api('/api/employer/profile')
      .then((p) => {
        setSaved(p)
        setForm(Object.fromEntries(Object.keys(EMPTY).map((k) => [k, p[k] ?? EMPTY[k]])))
      })
      .catch((err) => { if (err.status !== 404) setError(err.message) })
      .finally(() => setLoading(false))
  }, [])

  const update = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  async function save(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v.trim() || null]))
    body.account_kind = form.account_kind
    try {
      const p = await api('/api/employer/profile', { method: 'PUT', body })
      setSaved(p)
      toast(p.verification_status === 'approved' ? 'Saved.' : 'Saved. An admin will check your details.')
    } catch (err) {
      setError(err.message)
    }
    setBusy(false)
  }

  const status = saved && VERIFICATION[saved.verification_status]
  const blocked = saved?.verification_status === 'blocked'
  const input = 'mt-1 w-full rounded border border-gray-300 px-3 py-2 disabled:opacity-60'

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <EmployerTabs />
      {loading ? <p className="text-gray-500">Loading your company details</p> : (
        <div className="grid md:grid-cols-[1fr_280px] gap-8 items-start">
          <form onSubmit={save} className="bg-white border border-gray-200 rounded p-5 space-y-4">
            <h2 className="font-display text-2xl">{saved ? 'Your company' : 'Tell us about your company'}</h2>
            <fieldset className="text-sm">
              <legend className="mb-1">You are</legend>
              {[['company', 'HR or a hiring manager at the company itself'],
                ['agency', 'A recruitment agency hiring for client companies']].map(([v, label]) => (
                <label key={v} className="flex items-center gap-2">
                  <input type="radio" name="kind" checked={form.account_kind === v} disabled={blocked}
                         onChange={() => setForm({ ...form, account_kind: v })} className="accent-dusk" /> {label}
                </label>
              ))}
            </fieldset>
            <label className="block text-sm">{form.account_kind === 'agency' ? 'Agency name' : 'Company name'}
              <input required minLength={2} maxLength={120} value={form.company_name} onChange={update('company_name')}
                     disabled={blocked} className={input} />
            </label>
            <label className="block text-sm">Official work email
              <input required type="email" maxLength={254} placeholder="hr@yourcompany.com" value={form.official_email}
                     onChange={update('official_email')} disabled={blocked} className={input} />
              <span className="block mt-1 text-xs text-gray-500">
                An email on your company's own domain is approved faster than Gmail or Yahoo.
              </span>
            </label>
            <div className="grid sm:grid-cols-2 gap-4">
              <label className="block text-sm">Website
                <input type="url" maxLength={300} placeholder="https://" value={form.website} onChange={update('website')}
                       disabled={blocked} className={input} />
              </label>
              <label className="block text-sm">GSTIN or CIN (optional)
                <input maxLength={25} pattern="[A-Za-z0-9]+" title="Letters and numbers only" value={form.gst_or_cin}
                       onChange={update('gst_or_cin')} disabled={blocked} className={input} />
              </label>
            </div>
            {saved && !blocked && (
              <p className="text-xs text-gray-500">Changing your details sends them to an admin for approval again.</p>
            )}
            {error && <p className="text-sm text-sindoor">{error}</p>}
            <button disabled={busy || blocked} className="px-6 py-2.5 rounded bg-dusk text-white font-semibold disabled:opacity-50">
              {busy ? 'Saving' : saved ? 'Save changes' : 'Send for approval'}
            </button>
          </form>

          <aside className="space-y-4">
            <div className="bg-white border border-gray-200 rounded p-5">
              <h2 className="font-display text-xl">Approval</h2>
              {status ? (
                <>
                  <span className={`inline-block mt-2 px-2 py-0.5 rounded-sm text-sm font-medium ${status[1]}`}>{status[0]}</span>
                  <p className="mt-2 text-sm text-gray-600">{status[2]}</p>
                  {saved.rejection_reason && (
                    <p className="mt-2 text-sm"><span className="font-medium">Reason:</span> {saved.rejection_reason}</p>
                  )}
                </>
              ) : <p className="mt-2 text-sm text-gray-600">Not sent yet. Fill in the form to get started.</p>}
            </div>
            <div className="bg-white border border-gray-200 rounded p-5 text-sm text-gray-600">
              <h2 className="font-display text-xl text-ink">How it works</h2>
              <ol className="mt-2 space-y-2">
                {['Add your company details', 'An admin approves them', 'Post jobs (each is checked before it goes live)',
                  'See views and apply clicks for every job'].map((step, i) => (
                  <li key={step} className="flex gap-2">
                    <span className="inline-flex w-5 h-5 shrink-0 rounded-full bg-taxi text-ink text-xs font-semibold items-center justify-center">{i + 1}</span>
                    {step}
                  </li>
                ))}
              </ol>
              <p className="mt-3 flex gap-2 text-xs">
                <Icon name="flag" className="w-4 h-4 shrink-0 text-sindoor" />
                Never ask candidates for money. Posts asking for fees are rejected and the account is blocked.
              </p>
            </div>
          </aside>
        </div>
      )}
    </div>
  )
}
