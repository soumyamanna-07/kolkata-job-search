// Admin: syllabi sent by students and faculty, and the colleges they named.
// Syllabi from logged-in users are used at once ("in use, not checked"). Check the subject table
// against the text read from the file, fix it if needed, then approve it or remove it.
import { useCallback, useEffect, useState } from 'react'
import AdminTabs from '../components/AdminTabs'
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
      if (action === 'save') {
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
      </div>
    </div>
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
          Sent by logged-in students and faculty and used at once. Check them here: approved ones are shown first,
          removed ones are no longer used.
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
                      {semesterText(s)}{s.batch ? `, batch ${s.batch}` : ''} {'\u00b7'} {s.subjects} subjects {'\u00b7'} sent{' '}
                      {postedText(s.created_at)?.toLowerCase()}{s.submitted_by_email ? ` by ${s.submitted_by_email}` : ''}
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
