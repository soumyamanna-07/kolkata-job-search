// Share a job link (students, and college TPOs for campus drives). An admin checks it before it goes live.
import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useToast } from '../lib/toast'

const STATUS = { pending: ['Waiting for review', 'bg-amber-50 text-amber-900'],
  approved: ['Live on the site', 'bg-green-50 text-green-800'], rejected: ['Not accepted', 'bg-red-50 text-sindoor'] }

export default function ShareJobPage() {
  const toast = useToast()
  const [form, setForm] = useState({ url: '', company_name: '', title: '', note: '', submitter_type: 'user' })
  const [mine, setMine] = useState([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = () => api('/api/me/job-links').then(setMine).catch(() => {})
  useEffect(() => { load() }, [])

  const update = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  async function send(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v.trim() || null]))
    try {
      await api('/api/job-links', { method: 'POST', body })
      toast('Thank you! An admin will check the link.')
      setForm({ ...form, url: '', company_name: '', title: '', note: '' })
      load()
    } catch (err) {
      setError(err.message)
    }
    setBusy(false)
  }

  const input = 'mt-1 w-full rounded border border-gray-300 px-3 py-2'
  return (
    <div className="max-w-4xl mx-auto px-4 py-8 grid md:grid-cols-[1fr_300px] gap-8 items-start">
      <div>
        <h1 className="font-display text-4xl">Share a job</h1>
        <p className="mt-1 text-gray-600">
          Seen a Kolkata job, walk-in or campus drive? Share the link. An admin checks it, and then everyone can find it here.
        </p>
        <form onSubmit={send} className="mt-6 bg-white border border-gray-200 rounded p-5 space-y-4">
          <label className="block text-sm">Link to the job post or notice
            <input required type="url" maxLength={500} placeholder="https://" value={form.url} onChange={update('url')} className={input} />
          </label>
          <div className="grid sm:grid-cols-2 gap-4">
            <label className="block text-sm">Company (optional)
              <input maxLength={120} value={form.company_name} onChange={update('company_name')} className={input} />
            </label>
            <label className="block text-sm">Job title (optional)
              <input maxLength={120} value={form.title} onChange={update('title')} className={input} />
            </label>
          </div>
          <label className="block text-sm">Note for the admin (optional)
            <textarea rows={3} maxLength={500} placeholder="e.g. Campus drive on 20 October for the 2026 batch"
                      value={form.note} onChange={update('note')} className={input} />
          </label>
          <fieldset className="text-sm">
            <legend className="mb-1">I am</legend>
            {[['user', 'A student or job seeker'], ['tpo', 'A college placement officer (TPO)']].map(([v, label]) => (
              <label key={v} className="flex items-center gap-2">
                <input type="radio" name="who" checked={form.submitter_type === v}
                       onChange={() => setForm({ ...form, submitter_type: v })} className="accent-dusk" /> {label}
              </label>
            ))}
          </fieldset>
          {error && <p className="text-sm text-sindoor">{error}</p>}
          <button disabled={busy} className="px-6 py-2.5 rounded bg-dusk text-white font-semibold disabled:opacity-50">
            {busy ? 'Sending' : 'Share link'}
          </button>
        </form>
      </div>

      <aside className="bg-white border border-gray-200 rounded p-5">
        <h2 className="font-display text-xl">Links you shared</h2>
        {mine.length === 0 ? <p className="mt-2 text-sm text-gray-600">None yet.</p> : (
          <ul className="mt-3 space-y-3 text-sm">
            {mine.map((l) => (
              <li key={l.id}>
                <p className="truncate font-medium">{l.title || l.company_name || l.url}</p>
                <span className={`inline-block mt-0.5 px-2 py-0.5 rounded-sm text-xs ${STATUS[l.status]?.[1] || ''}`}>
                  {STATUS[l.status]?.[0] || l.status}
                </span>
                {l.rejection_reason && <p className="text-xs text-gray-500 mt-0.5">{l.rejection_reason}</p>}
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  )
}
