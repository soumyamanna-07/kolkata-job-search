// Admin: syllabi sent by students and faculty, and the colleges they named.
// Syllabi from logged-in users are used at once ("in use, not checked"). Check the subject table
// against the text read from the file, fix it if needed, then approve it or remove it.
// "Delete permanently" erases a syllabus completely (e.g. a test upload).
// Syllabus links: college syllabus files that the weekly fetcher reads into the Waiting list.
import { useCallback, useEffect, useState } from 'react'
import AdminTabs from '../components/AdminTabs'
import Modal from '../components/Modal'
import SubjectTable, { cleanSubjects } from '../components/SubjectTable'
import { api } from '../lib/api'
import { postedText } from '../lib/format'
import { useToast } from '../lib/toast'

const STATUSES = [['unverified', 'In use, not checked'], ['pending', 'Waiting'], ['approved', 'Approved'],
  ['rejected', 'Removed'], ['archived', 'Replaced'], ['all', 'All']]
const STATUS_LABEL = Object.fromEntries(STATUSES)
const STATUS_STYLE = {
  unverified: 'bg-amber-100 text-amber-900', pending: 'bg-amber-100 text-amber-900', approved: 'bg-green-100 text-green-800',
  rejected: 'bg-red-50 text-sindoor', archived: 'bg-gray-100 text-gray-600',
}
const TO_CHECK = ['pending', 'unverified']
const input = 'mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm'

function semesterText(s) {
  return s.semester ? `Semester ${s.semester}` : 'All semesters'
}

// ---------------------------------------------------------------- one syllabus, opened
function SyllabusCheck({ id, onDone, onClose }) {
  const toast = useToast()
  const [data, setData] = useState(null)
  const [subjects, setSubjects] = useState([])
  const [form, setForm] = useState({ department: '', batch: '', semester: '', whole: false, note: '' })
  const [changed, setChanged] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [showText, setShowText] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  useEffect(() => {
    api(`/api/admin/syllabi/${id}`).then((d) => {
      setData(d)
      setSubjects(d.subject_list)
      setForm({ department: d.department, batch: d.batch || '', semester: d.semester ?? '', whole: d.semester == null, note: '' })
    }).catch((e) => setError(e.message))
  }, [id])

  const editable = data && ['pending', 'unverified', 'approved'].includes(data.status)
  const update = (key) => (e) => setForm({ ...form, [key]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  async function saveTable() {
    const clean = cleanSubjects(subjects)
    if (!clean.length) { setError('Add at least one subject.'); return null }
    const d = await api(`/api/admin/syllabi/${id}/subjects`, { method: 'PUT', body: { subjects: clean } })
    setData(d)
    setSubjects(d.subject_list)
    setChanged(false)
    return d
  }

  async function run(action) {
    setBusy(true)
    setError('')
    try {
      if (action === 'delete') {
        await api(`/api/admin/syllabi/${id}`, { method: 'DELETE' })
        toast('Syllabus deleted permanently.')
        onDone()
      } else if (action === 'save') {
        if (await saveTable()) toast('Subject table saved.')
      } else if (action === 'reject') {
        await api(`/api/admin/syllabi/${id}/review`, { method: 'POST', body: { decision: 'reject', note: form.note.trim() } })
        toast('Syllabus removed. The sender sees your reason.')
        onDone()
      } else {
        if (changed && !(await saveTable())) { setBusy(false); return }
        await api(`/api/admin/syllabi/${id}/review`, {
          method: 'POST',
          body: { decision: 'approve', department: form.department.trim(), batch: form.batch.trim(),
            semester: form.whole || form.semester === '' ? null : Number(form.semester), whole_course: form.whole,
            note: form.note.trim() || null },
        })
        toast('Approved. It is now shown as checked.')
        onDone()
      }
    } catch (e) {
      setError(e.message)
    }
    setBusy(false)
  }

  if (!data) return <p className="p-4 text-sm text-gray-500">{error || 'Loading'}</p>

  return (
    <div className="p-4 sm:p-5 bg-paper border-t border-gray-200 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="text-sm text-gray-700">
          {data.source_url && (
            <span className="block">
              Fetched from the college website:{' '}
              <a href={data.source_url} target="_blank" rel="noreferrer" className="text-dusk underline break-all">{data.source_url}</a>
            </span>
          )}
          File: <strong>{data.file_name || 'not kept'}</strong> {'\u00b7'} {data.raw_text_length.toLocaleString('en-IN')} characters read
          {data.college_status === 'pending' && <span className="ml-2 px-2 py-0.5 rounded-sm bg-amber-100 text-amber-900">New college: approving this also approves the college</span>}
        </p>
        <button onClick={onClose} className="text-sm text-dusk underline">Close</button>
      </div>

      <div>
        <button type="button" onClick={() => setShowText(!showText)} className="text-sm text-dusk underline" aria-expanded={showText}>
          {showText ? 'Hide the text read from the file' : 'Show the text read from the file'}
        </button>
        {showText && (
          <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap text-xs bg-white border border-gray-200 rounded p-3">
            {data.raw_text}{data.raw_text_length > data.raw_text.length ? '\n\n[... the rest is not shown]' : ''}
          </pre>
        )}
      </div>

      {editable ? (
        <SubjectTable subjects={subjects} onChange={(s) => { setSubjects(s); setChanged(true) }} showSkills
                      caption={`${subjects.length} subjects. Skills are found again when you save.`} />
      ) : (
        <p className="text-sm text-gray-600">This syllabus is {data.status}; its subjects can no longer be changed.</p>
      )}

      {TO_CHECK.includes(data.status) && (
        <div className="grid sm:grid-cols-4 gap-3 text-sm">
          <label className="block sm:col-span-2">Department
            <input value={form.department} onChange={update('department')} maxLength={120} className={input} />
          </label>
          <label className="block">Batch
            <input value={form.batch} onChange={update('batch')} maxLength={40} placeholder="e.g. 2023-27" className={input} />
          </label>
          <div>
            <label className="block">Semester
              <input type="number" min="1" max="10" value={form.semester} onChange={update('semester')} disabled={form.whole} className={input} />
            </label>
            <label className="mt-1 flex items-center gap-1.5 text-xs">
              <input type="checkbox" checked={form.whole} onChange={update('whole')} /> Whole course (all semesters)
            </label>
          </div>
          <label className="block sm:col-span-4">Note to the sender (needed when removing)
            <input value={form.note} onChange={update('note')} maxLength={1000}
                   placeholder="e.g. This is the 2018 syllabus; please send the current one." className={input} />
          </label>
        </div>
      )}

      {error && <p className="p-2 rounded bg-red-50 text-sindoor text-sm">{error}</p>}
      <div className="flex flex-wrap gap-2 text-sm">
        {TO_CHECK.includes(data.status) && (
          <button disabled={busy} onClick={() => run('approve')} className="px-4 py-2 rounded bg-hooghly text-white font-semibold disabled:opacity-50">
            {changed ? 'Save table and approve' : 'Approve'}
          </button>
        )}
        {editable && changed && (
          <button disabled={busy} onClick={() => run('save')} className="px-4 py-2 rounded border border-gray-300 bg-white hover:border-dusk disabled:opacity-50">
            Save table only
          </button>
        )}
        {TO_CHECK.includes(data.status) && (
          <button disabled={busy || form.note.trim().length < 3} onClick={() => run('reject')}
                  title={form.note.trim().length < 3 ? 'Write a note to the sender first' : undefined}
                  className="px-4 py-2 rounded border border-gray-300 bg-white hover:bg-red-50 disabled:opacity-50">
            Remove
          </button>
        )}
        <button disabled={busy} onClick={() => setConfirmDelete(true)}
                className="px-4 py-2 rounded border border-gray-300 bg-white text-sindoor hover:bg-red-50 disabled:opacity-50 sm:ml-auto">
          Delete permanently
        </button>
      </div>
      {confirmDelete && (
        <Modal title="Delete this syllabus for good?" onClose={() => setConfirmDelete(false)}>
          <p className="text-sm text-gray-600">
            {data.college_name}, {data.department}: the subjects and the text read from the file are erased and cannot be
            brought back. Use Remove instead if you only want to stop it being used.
          </p>
          <div className="mt-4 flex gap-2">
            <button onClick={() => { setConfirmDelete(false); run('delete') }} className="px-4 py-2 rounded bg-sindoor text-white font-semibold">
              Delete permanently
            </button>
            <button onClick={() => setConfirmDelete(false)} className="px-4 py-2 rounded border border-gray-300">Keep it</button>
          </div>
        </Modal>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- syllabus links (read every week)
const LINK_STATUS = {
  new: ['New file added to Waiting', 'bg-green-100 text-green-800'],
  unchanged: ['No change', 'bg-gray-100 text-gray-600'],
  blocked: ['Not allowed / no answer', 'bg-amber-100 text-amber-900'],
  error: ['Problem', 'bg-red-50 text-sindoor'],
}
const emptyLink = { college_id: '', department: '', batch: '', semester: '', url: '' }

function SyllabusLinks({ colleges }) {
  const toast = useToast()
  const [links, setLinks] = useState(null)
  const [form, setForm] = useState(emptyLink)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    api('/api/admin/syllabus-sources').then(setLinks).catch((e) => setError(e.message))
  }, [])
  useEffect(() => { load() }, [load])

  async function call(work, message) {
    setBusy(true)
    setError('')
    try {
      await work()
      toast(message)
      load()
      return true
    } catch (e) {
      setError(e.message)
      return false
    } finally {
      setBusy(false)
    }
  }

  async function add(e) {
    e.preventDefault()
    const body = { college_id: form.college_id, url: form.url.trim(), department: form.department.trim(),
      batch: form.batch.trim() || null, semester: form.semester === '' ? null : Number(form.semester) }
    if (await call(() => api('/api/admin/syllabus-sources', { method: 'POST', body }), 'Link added. The next weekly check reads it.')) {
      setForm({ ...emptyLink, college_id: form.college_id })
    }
  }

  const field = (key) => ({ value: form[key], onChange: (e) => setForm({ ...form, [key]: e.target.value }) })
  const usable = (colleges || []).filter((c) => c.status !== 'rejected')

  return (
    <section className="mt-10">
      <h2 className="font-display text-2xl mb-1">Syllabus links</h2>
      <p className="text-sm text-gray-600 mb-3">
        Links to syllabus PDF or Word files on college websites. Every week they are read (only when the
        website&apos;s robots.txt allows it); a new or changed file goes to the Waiting tab above and is used only after you approve it.
      </p>

      <form onSubmit={add} className="p-4 bg-white border border-gray-200 rounded grid sm:grid-cols-6 gap-3 text-sm">
        <label className="block sm:col-span-2">College
          <select required {...field('college_id')} className={input}>
            <option value="">Choose a college</option>
            {usable.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <label className="block sm:col-span-2">Department
          <input required minLength={2} maxLength={120} {...field('department')} placeholder="e.g. CSE (AI & ML)" className={input} />
        </label>
        <label className="block">Batch
          <input maxLength={40} {...field('batch')} placeholder="optional" className={input} />
        </label>
        <label className="block">Semester
          <input type="number" min="1" max="10" {...field('semester')} placeholder="all" className={input} />
        </label>
        <label className="block sm:col-span-5">Link to the PDF or Word file
          <input required type="url" maxLength={500} {...field('url')} placeholder="https://college.edu/.../syllabus.pdf" className={input} />
        </label>
        <div className="sm:self-end">
          <button disabled={busy} className="w-full px-4 py-2 rounded bg-dusk text-white font-semibold disabled:opacity-50">Add link</button>
        </div>
      </form>
      {error && <p className="mt-2 p-2 rounded bg-red-50 text-sindoor text-sm">{error}</p>}

      {links && links.length === 0 && <p className="mt-3 text-sm text-gray-600">No links yet.</p>}
      {links && links.length > 0 && (
        <ul className="mt-3 bg-white border border-gray-200 rounded divide-y divide-gray-200">
          {links.map((l) => {
            const [label, style] = LINK_STATUS[l.last_status] || ['Not checked yet', 'bg-gray-100 text-gray-600']
            return (
              <li key={l.id} className={`p-4 ${l.enabled ? '' : 'opacity-60'}`}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="font-semibold">
                      {l.college_name} {'\u00b7'} {l.department}
                      <span className="font-normal text-gray-600">
                        {l.semester ? `, semester ${l.semester}` : ', all semesters'}{l.batch ? `, batch ${l.batch}` : ''}
                      </span>
                    </p>
                    <a href={l.url} target="_blank" rel="noreferrer" className="text-sm text-dusk underline break-all">{l.url}</a>
                    <p className="text-sm text-gray-600 mt-1">
                      {l.last_checked_at ? `Last checked ${postedText(l.last_checked_at)?.toLowerCase()}` : 'Read at the next weekly check'}
                      {l.enabled ? '' : ' (switched off)'}
                    </p>
                    {l.last_error && <p className="text-sm text-sindoor mt-1">{l.last_error}</p>}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className={`px-2 py-0.5 rounded-sm ${style}`}>{label}</span>
                    <button disabled={busy} onClick={() => call(() => api(`/api/admin/syllabus-sources/${l.id}`,
                      { method: 'PATCH', body: { enabled: !l.enabled } }), l.enabled ? 'Link switched off.' : 'Link switched on.')}
                            className="px-3 py-1 rounded border border-gray-300 hover:border-dusk disabled:opacity-50">
                      {l.enabled ? 'Switch off' : 'Switch on'}
                    </button>
                    <button disabled={busy} onClick={() => call(() => api(`/api/admin/syllabus-sources/${l.id}`, { method: 'DELETE' }),
                      'Link removed. Syllabi already fetched from it stay.')}
                            className="px-3 py-1 rounded border border-gray-300 hover:bg-red-50 disabled:opacity-50">
                      Remove link
                    </button>
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

// ---------------------------------------------------------------- colleges
function College({ c, onSaved }) {
  const toast = useToast()
  const [edit, setEdit] = useState(false)
  const [form, setForm] = useState({ short_name: c.short_name || '', university: c.university || '', syllabus_url: c.syllabus_url || '' })
  const [error, setError] = useState('')

  async function save(changes, message) {
    setError('')
    try {
      await api(`/api/admin/colleges/${c.id}`, { method: 'PATCH', body: changes })
      toast(message)
      setEdit(false)
      onSaved()
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <li className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-semibold">{c.name}{c.short_name ? ` (${c.short_name})` : ''}</p>
          <p className="text-sm text-gray-600">
            {c.university || 'University not set'} {'\u00b7'} {c.approved_syllabi} approved, {c.pending_syllabi} waiting
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className={`px-2 py-0.5 rounded-sm ${STATUS_STYLE[c.status]}`}>{c.status}</span>
          {c.status !== 'approved' && <button onClick={() => save({ status: 'approved' }, 'College approved.')} className="px-3 py-1 rounded bg-hooghly text-white">Approve</button>}
          {c.status === 'pending' && <button onClick={() => save({ status: 'rejected' }, 'College name rejected.')} className="px-3 py-1 rounded border border-gray-300 hover:bg-red-50">Reject</button>}
          <button onClick={() => setEdit(!edit)} className="px-3 py-1 rounded border border-gray-300 hover:border-dusk">{edit ? 'Cancel' : 'Edit'}</button>
        </div>
      </div>
      {edit && (
        <form onSubmit={(e) => {
          e.preventDefault()
          save({ short_name: form.short_name.trim() || null, university: form.university.trim() || null,
            syllabus_url: form.syllabus_url.trim() || null }, 'College saved.')
        }} className="mt-3 grid sm:grid-cols-3 gap-3 text-sm">
          <label className="block">Short name
            <input value={form.short_name} maxLength={40} onChange={(e) => setForm({ ...form, short_name: e.target.value })} className={input} />
          </label>
          <label className="block">University
            <input value={form.university} maxLength={200} onChange={(e) => setForm({ ...form, university: e.target.value })} placeholder="e.g. MAKAUT" className={input} />
          </label>
          <label className="block">Syllabus page or PDF (for automatic reading later)
            <input type="url" value={form.syllabus_url} maxLength={500} onChange={(e) => setForm({ ...form, syllabus_url: e.target.value })} placeholder="https://" className={input} />
          </label>
          <div className="sm:col-span-3"><button className="px-4 py-2 rounded bg-dusk text-white font-semibold">Save</button></div>
        </form>
      )}
      {error && <p className="mt-2 p-2 rounded bg-red-50 text-sindoor text-sm">{error}</p>}
    </li>
  )
}

export default function AdminSyllabiPage() {
  const [status, setStatus] = useState('unverified')
  const [list, setList] = useState(null)
  const [colleges, setColleges] = useState(null)
  const [open, setOpen] = useState(null)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    setError('')
    Promise.all([api('/api/admin/syllabi', { params: { status } }), api('/api/admin/colleges')])
      .then(([s, c]) => { setList(s); setColleges(c) })
      .catch((e) => setError(e.message))
  }, [status])
  useEffect(() => { load() }, [load])

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <AdminTabs />
      {error && <p className="p-4 rounded bg-red-50 text-sindoor text-sm">{error}</p>}

      <section>
        <h2 className="font-display text-2xl mb-1">Syllabi</h2>
        <p className="text-sm text-gray-600 mb-3">
          Sent by logged-in students and faculty (used at once), or fetched from college websites (Waiting: used only
          after you approve). Approved ones are shown first; removed ones are no longer used.
        </p>
        <div className="flex flex-wrap gap-1 mb-3" role="tablist" aria-label="Syllabus status">
          {STATUSES.map(([v, t]) => (
            <button key={v} role="tab" aria-selected={status === v} onClick={() => { setStatus(v); setOpen(null) }}
                    className={`px-3 py-1.5 rounded text-sm ${status === v ? 'bg-dusk text-white' : 'bg-white border border-gray-300 hover:border-dusk'}`}>
              {t}
            </button>
          ))}
        </div>
        {!list && !error && <p className="text-gray-500">Loading</p>}
        {list && list.length === 0 && <p className="p-6 bg-white border border-gray-200 rounded text-sm text-gray-600">Nothing here.</p>}
        {list && list.length > 0 && (
          <ul className="bg-white border border-gray-200 rounded divide-y divide-gray-200">
            {list.map((s) => (
              <li key={s.id}>
                <div className="p-4 sm:p-5 flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-semibold">{s.college_name} {'\u00b7'} {s.department}</p>
                    <p className="text-sm text-gray-600">
                      {semesterText(s)}{s.batch ? `, batch ${s.batch}` : ''} {'\u00b7'} {s.subjects} subjects {'\u00b7'} {s.source === 'website' ? 'fetched' : 'sent'}{' '}
                      {postedText(s.created_at)?.toLowerCase()}
                      {s.source === 'website' ? ' from the college website' : s.submitted_by_email ? ` by ${s.submitted_by_email}` : ''}
                    </p>
                    {s.review_note && <p className="text-sm text-gray-700 mt-1">Note: {s.review_note}</p>}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`px-2 py-0.5 rounded-sm text-sm ${STATUS_STYLE[s.status]}`}>{STATUS_LABEL[s.status]}</span>
                    <button onClick={() => setOpen(open === s.id ? null : s.id)} aria-expanded={open === s.id}
                            className="px-3 py-1.5 rounded border border-gray-300 text-sm hover:border-dusk">
                      {open === s.id ? 'Close' : TO_CHECK.includes(s.status) ? 'Check' : 'Open'}
                    </button>
                  </div>
                </div>
                {open === s.id && <SyllabusCheck id={s.id} onClose={() => setOpen(null)} onDone={() => { setOpen(null); load() }} />}
              </li>
            ))}
          </ul>
        )}
      </section>

      <SyllabusLinks colleges={colleges} />

      <section className="mt-10">
        <h2 className="font-display text-2xl mb-1">Colleges</h2>
        <p className="text-sm text-gray-600 mb-3">Names typed by users appear here and in the college suggestions at once. Reject a wrong or duplicate name to hide it.</p>
        {colleges && (
          <ul className="bg-white border border-gray-200 rounded divide-y divide-gray-200">
            {colleges.map((c) => <College key={c.id} c={c} onSaved={load} />)}
          </ul>
        )}
      </section>
    </div>
  )
}
