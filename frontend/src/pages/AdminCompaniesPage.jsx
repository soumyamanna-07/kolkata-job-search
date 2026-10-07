// Admin: the Company List. Companies with a Greenhouse / Lever / Ashby / Workable board code, or a careers
// page, are read directly by the daily pipeline (better data than aggregators). Changes go to the audit log.
import { useCallback, useEffect, useState } from 'react'
import AdminTabs from '../components/AdminTabs'
import Modal from '../components/Modal'
import { api } from '../lib/api'
import { postedText } from '../lib/format'
import { useToast } from '../lib/toast'

const BOARDS = { greenhouse: 'boards.greenhouse.io/CODE', lever: 'jobs.lever.co/CODE', ashby: 'jobs.ashbyhq.com/CODE',
  workable: 'apply.workable.com/CODE' }
const PLATFORMS = { greenhouse: 'Greenhouse', lever: 'Lever', ashby: 'Ashby', workable: 'Workable',
  smartrecruiters: 'SmartRecruiters', zoho_recruit: 'Zoho Recruit', freshteam: 'Freshteam', keka: 'Keka',
  darwinbox: 'Darwinbox', government: 'Government recruitment page', other: 'Other / own careers page' }
const EMPTY = { name: '', website: '', careers_url: '', ats_platform: 'other', ats_token: '', notes: '', is_active: true }
const input = 'mt-1 w-full rounded border border-gray-300 px-3 py-2'

const toBody = (f) => ({ name: f.name.trim(), website: f.website.trim() || null, careers_url: f.careers_url.trim() || null,
  ats_platform: f.ats_platform, ats_token: f.ats_token.trim() || null, notes: f.notes.trim() || null, is_active: f.is_active })
const toForm = (c) => Object.fromEntries(Object.keys(EMPTY).map((k) => [k, c[k] ?? EMPTY[k]]))

function CompanyForm({ company, onSaved, onCancel }) {
  const toast = useToast()
  const [form, setForm] = useState(company ? toForm(company) : EMPTY)
  const [check, setCheck] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const update = (key) => (e) => { setForm({ ...form, [key]: e.target.value }); if (key !== 'notes') setCheck(null) }
  const board = BOARDS[form.ats_platform]

  async function checkBoard() {
    setCheck({ loading: true })
    try {
      setCheck(await api('/api/admin/companies/check-board', { method: 'POST',
        body: { ats_platform: form.ats_platform, ats_token: form.ats_token.trim() } }))
    } catch (err) {
      setCheck({ ok: false, error: err.message })
    }
  }

  async function save(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const saved = await api(company ? `/api/admin/companies/${company.id}` : '/api/admin/companies',
        { method: company ? 'PUT' : 'POST', body: toBody(form) })
      toast(company ? `${saved.name} saved.` : `${saved.name} added. The next pipeline run collects its jobs.`)
      onSaved()
    } catch (err) {
      setError(err.message)
    }
    setBusy(false)
  }

  return (
    <form onSubmit={save} className="bg-white border border-gray-200 rounded p-5 space-y-3 text-sm">
      <h2 className="font-display text-xl">{company ? `Edit ${company.name}` : 'Add a company'}</h2>
      <div className="grid sm:grid-cols-2 gap-3">
        <label className="block">Company name
          <input required minLength={2} maxLength={120} value={form.name} onChange={update('name')} className={input} />
        </label>
        <label className="block">Website (optional)
          <input type="url" maxLength={300} placeholder="https://" value={form.website} onChange={update('website')} className={input} />
        </label>
        <label className="block">Where it posts jobs
          <select value={form.ats_platform} onChange={update('ats_platform')} className={input}>
            {Object.entries(PLATFORMS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        {board ? (
          <label className="block">Board code
            <div className="flex gap-2">
              <input required maxLength={100} pattern="[A-Za-z0-9][A-Za-z0-9_.\-]*" value={form.ats_token}
                     onChange={update('ats_token')} className={input} placeholder="e.g. abctech" />
              <button type="button" onClick={checkBoard} disabled={!form.ats_token.trim() || check?.loading}
                      className="mt-1 px-3 rounded border border-gray-300 hover:border-dusk whitespace-nowrap disabled:opacity-50">
                {check?.loading ? 'Checking' : 'Check'}
              </button>
            </div>
            <span className="block mt-1 text-xs text-gray-500">The CODE part of {board}</span>
          </label>
        ) : (
          <label className="block">{form.ats_platform === 'government' ? 'Official recruitment page' : 'Careers page (optional)'}
            <input type="url" maxLength={500} required={form.ats_platform === 'government'}
                   placeholder={form.ats_platform === 'government' ? 'https://office.gov.in/recruitment' : 'https://company.com/careers'}
                   value={form.careers_url} onChange={update('careers_url')} className={input} />
            <span className="block mt-1 text-xs text-gray-500">
              {form.ats_platform === 'government'
                ? 'Read daily: current recruitment notices (with a last date) are shown as Government jobs.'
                : 'Read daily if it tags jobs for Google Jobs.'}
            </span>
          </label>
        )}
      </div>
      {check && !check.loading && (
        <div className={`p-3 rounded ${check.ok ? 'bg-green-50' : 'bg-red-50 text-sindoor'}`}>
          {check.ok ? (
            <>
              <p><span className="font-semibold">Board works.</span> {check.jobs} open jobs, {check.kolkata_jobs} in Kolkata.</p>
              {check.sample_titles.length > 0 && <p className="mt-1 text-gray-700">For example: {check.sample_titles.join('; ')}</p>}
            </>
          ) : <p>{check.error || 'This board code did not work.'}</p>}
        </div>
      )}
      <label className="block">Notes (optional)
        <input maxLength={500} value={form.notes} onChange={update('notes')} className={input} placeholder="e.g. Office in Sector V" />
      </label>
      {error && <p className="p-2 rounded bg-red-50 text-sindoor">{error}</p>}
      <div className="flex gap-2">
        <button disabled={busy} className="px-4 py-2 rounded bg-dusk text-white font-semibold disabled:opacity-50">
          {busy ? 'Saving' : company ? 'Save changes' : 'Add company'}
        </button>
        <button type="button" onClick={onCancel} className="px-4 py-2 rounded border border-gray-300">Cancel</button>
      </div>
    </form>
  )
}

export default function AdminCompaniesPage() {
  const toast = useToast()
  const [list, setList] = useState(null)
  const [q, setQ] = useState('')
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null)       // null, 'new' or a company
  const [pausing, setPausing] = useState(null)

  const load = useCallback((search = '') => {
    api('/api/admin/companies', { params: { q: search.trim() } }).then(setList).catch((err) => setError(err.message))
  }, [])
  useEffect(() => { load() }, [load])

  async function setActive(company, active) {
    try {
      await api(`/api/admin/companies/${company.id}`, { method: 'PUT', body: { ...toBody(toForm(company)), is_active: active } })
      toast(active ? `${company.name} will be collected again.` : `${company.name} paused. Its collected jobs were closed.`)
      setPausing(null)
      load(q)
    } catch (err) {
      toast(err.message)
    }
  }

  const done = () => { setEditing(null); load(q) }

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <AdminTabs />
      <div className="flex flex-wrap items-end justify-between gap-3 mb-4">
        <form onSubmit={(e) => { e.preventDefault(); load(q) }} className="flex gap-2">
          <label className="sr-only" htmlFor="company-search">Search companies</label>
          <input id="company-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name"
                 className="rounded border border-gray-300 px-3 py-2 text-sm bg-white" />
          <button className="px-4 py-2 rounded border border-gray-300 text-sm">Search</button>
        </form>
        {editing === null && (
          <button onClick={() => setEditing('new')} className="px-4 py-2 rounded bg-taxi text-ink font-semibold text-sm hover:bg-taxi-deep">
            Add a company
          </button>
        )}
      </div>

      {editing && <div className="mb-6"><CompanyForm company={editing === 'new' ? null : editing} onSaved={done} onCancel={() => setEditing(null)} /></div>}
      {error && <p className="p-4 rounded bg-red-50 text-sindoor text-sm">{error}</p>}
      {!list && !error && <p className="text-gray-500">Loading</p>}

      {list && (
        list.length === 0 ? <p className="text-sm text-gray-600">No companies found.</p> : (
          <div className="bg-white border border-gray-200 rounded overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-gray-600 border-b border-gray-200">
                  <th className="px-4 py-2 font-medium">Company</th>
                  <th className="px-4 py-2 font-medium">Job board</th>
                  <th className="px-4 py-2 font-medium">Collected daily</th>
                  <th className="px-4 py-2 font-medium text-right">Open jobs</th>
                  <th className="px-4 py-2 font-medium">Last job seen</th>
                  <th className="px-4 py-2"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {list.map((c) => (
                  <tr key={c.id} className={`border-b border-gray-100 ${c.is_active ? '' : 'opacity-60'}`}>
                    <td className="px-4 py-2">
                      <p className="font-medium">{c.name}</p>
                      {c.notes && <p className="text-xs text-gray-500">{c.notes}</p>}
                    </td>
                    <td className="px-4 py-2">{PLATFORMS[c.ats_platform] || c.ats_platform}{c.ats_token ? ` (${c.ats_token})` : ''}</td>
                    <td className="px-4 py-2">
                      {!c.is_active ? <span className="text-gray-600">Paused</span>
                        : c.collected ? <span className="text-green-700 font-medium">Yes</span>
                          : <span className="text-amber-800">No (add a board code or careers page)</span>}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">{c.open_jobs}</td>
                    <td className="px-4 py-2 text-gray-600">{postedText(c.last_job_seen_at) || '-'}</td>
                    <td className="px-4 py-2 whitespace-nowrap text-right">
                      <button onClick={() => setEditing(c)} className="px-2 py-1 rounded hover:bg-paper text-dusk">Edit</button>
                      {c.is_active
                        ? <button onClick={() => setPausing(c)} className="px-2 py-1 rounded hover:bg-red-50 text-sindoor">Pause</button>
                        : <button onClick={() => setActive(c, true)} className="px-2 py-1 rounded hover:bg-paper text-dusk">Resume</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {pausing && (
        <Modal title={`Pause ${pausing.name}?`} onClose={() => setPausing(null)}>
          <p className="text-sm text-gray-600">
            The pipeline stops reading its job board, and its {pausing.open_jobs} collected open jobs are closed now.
            Jobs posted by recruiters are not touched. You can resume it any time.
          </p>
          <div className="mt-4 flex gap-2">
            <button onClick={() => setActive(pausing, false)} className="px-4 py-2 rounded bg-sindoor text-white font-semibold">Pause</button>
            <button onClick={() => setPausing(null)} className="px-4 py-2 rounded border border-gray-300">Cancel</button>
          </div>
        </Modal>
      )}
    </div>
  )
}
