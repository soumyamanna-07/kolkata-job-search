// College syllabus check (Curriculum Gap Report) for students and faculty.
// 1. Pick college + department + semester: an admin-approved syllabus is used first.
// 2. Or upload your syllabus (PDF / Word): a quick check, nothing is stored.
// 3. The report compares the syllabus with what live Kolkata jobs ask for, shows the gaps
//    as charts, what to learn now, and which extra classes a college could arrange.
// 4. Logged-in users can send their syllabus so it is used for everyone (after an admin checks it).
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import SubjectTable, { cleanSubjects } from '../components/SubjectTable'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import Icon from '../lib/icons'
import { loginUrl } from '../lib/next'
import { useToast } from '../lib/toast'
import './curriculum.css'

const STATUS = {
  covered: { label: 'Taught', mark: '\u2713', cls: 'cg-covered', note: 'the syllabus teaches it properly' },
  elective_only: { label: 'Elective only', mark: '\u25c7', cls: 'cg-elective', note: 'only in an elective choice' },
  partial: { label: 'Partly taught', mark: '\u25d0', cls: 'cg-partial', note: 'touched on, not taught in depth' },
  missing: { label: 'Not taught', mark: '\u2715', cls: 'cg-missing', note: 'not in the syllabus' },
}
const TREND = { rising: 'rising \u2197', falling: 'falling \u2198', steady: 'steady', unknown: 'not enough data yet' }
const SEMESTERS = [1, 2, 3, 4, 5, 6, 7, 8]
const input = 'mt-1 w-full rounded border border-gray-300 px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-dusk'
const pct = (v) => `${Math.round(v)}%`

function Panel({ title, note, children, className = '' }) {
  return (
    <section className={`bg-white border border-gray-200 rounded p-5 ${className}`}>
      <h2 className="font-display text-2xl">{title}</h2>
      {note && <p className="text-sm text-gray-600 mt-1 mb-4 max-w-3xl">{note}</p>}
      {!note && <div className="mb-4" />}
      {children}
    </section>
  )
}

// ---------------------------------------------------------------- charts
function StatusLegend() {
  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-gray-700 mb-3" aria-label="What the colours mean">
      {Object.entries(STATUS).map(([key, s]) => (
        <li key={key} className="inline-flex items-center gap-1.5">
          <span className={`inline-block w-3 h-3 rounded-sm ${s.cls}`} aria-hidden="true" />{s.label}
          <span aria-hidden="true" className="text-gray-500">{s.mark}</span>
        </li>
      ))}
    </ul>
  )
}

// horizontal bars: share of jobs asking for each skill, the 95% range as a thin line,
// coloured (and labelled in words) by whether the syllabus teaches it
function DemandChart({ skills }) {
  const rows = skills.slice(0, 15)
  const max = Math.max(...rows.map((r) => r.ci[1]), 1)
  return (
    <div>
      <StatusLegend />
      <ul className="space-y-1.5">
        {rows.map((r) => {
          const s = STATUS[r.status]
          const taught = r.taught_in.filter((t) => !t.elective).map((t) => `${t.subject} (Sem ${t.semester ?? '-'})`)
          const electives = r.taught_in.filter((t) => t.elective).map((t) => t.option)
          return (
            <li key={r.skill} tabIndex={0} className="cg-row relative grid grid-cols-[6.5rem_1fr_3rem_1rem] sm:grid-cols-[9rem_1fr_3rem_8rem] items-center gap-2 sm:gap-3 text-sm rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-dusk"
                aria-label={`${r.skill}: ${r.share}% of jobs, ${s.label}`}>
              <span className="truncate">{r.skill}</span>
              <span className="relative h-4 cg-track rounded-r">
                <span className={`absolute left-0 top-0 h-4 rounded-r ${s.cls}`} style={{ width: `${(r.share / max) * 100}%` }} />
                <span className="absolute top-1/2 h-[2px] -mt-px cg-whisker opacity-60"
                      style={{ left: `${(r.ci[0] / max) * 100}%`, width: `${Math.max(((r.ci[1] - r.ci[0]) / max) * 100, 0.5)}%` }} />
              </span>
              <span className="tabular-nums text-right text-gray-800">{r.share}%</span>
              <span className="text-gray-700" title={s.label}><span aria-hidden="true">{s.mark}</span><span className="hidden sm:inline"> {s.label}</span></span>
              <span className="cg-tip hidden absolute z-10 left-0 right-0 sm:left-36 sm:right-auto sm:w-72 top-full mt-1 rounded bg-ink text-white text-xs p-2.5 shadow-lg">
                <strong>{r.skill}</strong>: {r.jobs} jobs ({r.share}%, likely {r.ci[0]}-{r.ci[1]}%). Trend: {TREND[r.trend]}.<br />
                {s.label}: {s.note}.
                {taught.length > 0 && <><br />Taught in: {taught.join(', ')}</>}
                {electives.length > 0 && <><br />Elective choice: {electives.join(', ')}</>}
              </span>
            </li>
          )
        })}
      </ul>
      <p className="text-xs text-gray-500 mt-3">
        Bar = share of relevant open jobs asking for the skill. Thin line = the likely range (95% confidence). Hover or tab to a row for details.
      </p>
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-dusk">Show as a table</summary>
        <div className="overflow-x-auto mt-2">
          <table className="w-full text-sm">
            <thead className="text-left text-gray-600"><tr>
              <th className="p-1.5">Skill</th><th className="p-1.5">Jobs</th><th className="p-1.5">Share</th>
              <th className="p-1.5">Likely range</th><th className="p-1.5">Trend</th><th className="p-1.5">In the syllabus</th>
            </tr></thead>
            <tbody className="divide-y divide-gray-100">
              {skills.map((r) => (
                <tr key={r.skill}>
                  <td className="p-1.5">{r.skill}</td><td className="p-1.5 tabular-nums">{r.jobs}</td>
                  <td className="p-1.5 tabular-nums">{r.share}%</td><td className="p-1.5 tabular-nums">{r.ci[0]}-{r.ci[1]}%</td>
                  <td className="p-1.5">{TREND[r.trend]}</td><td className="p-1.5">{STATUS[r.status].label}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  )
}

// columns: how much of the market's demand is covered by the end of each semester
function SemesterChart({ semesters, current }) {
  return (
    <div>
      <div className="flex items-end gap-2 sm:gap-4 h-44 border-b border-gray-300" role="img"
           aria-label={`Share of job demand covered by the end of each semester: ${semesters.map((s) => `semester ${s.semester} ${s.coverage_upto}%`).join(', ')}`}>
        {semesters.map((s) => (
          <div key={s.semester} tabIndex={0} className="cg-col group relative flex-1 h-full flex flex-col justify-end items-center focus:outline-none">
            <span className="text-xs tabular-nums text-gray-700 mb-1">{pct(s.coverage_upto)}</span>
            <div className={`w-full max-w-[24px] rounded-t ${s.semester === current ? 'bg-taxi' : 'bar'}`}
                 style={{ height: `${Math.max(s.coverage_upto, 1)}%` }} />
            <span className="cg-tip hidden absolute bottom-full mb-1 whitespace-nowrap rounded bg-ink text-white text-xs px-2 py-1">
              Sem {s.semester}: {s.job_linked_subjects} of {s.subjects} subjects match job skills
            </span>
          </div>
        ))}
      </div>
      <div className="flex gap-2 sm:gap-4 mt-1">
        {semesters.map((s) => (
          <span key={s.semester} className={`flex-1 text-center text-xs ${s.semester === current ? 'font-semibold text-ink' : 'text-gray-500'}`}>
            Sem {s.semester}
          </span>
        ))}
      </div>
    </div>
  )
}

// single-series horizontal bars (subjects, class reach)
function Bars({ rows }) {
  const max = Math.max(...rows.map((r) => r.value), 1)
  return (
    <ul className="space-y-2">
      {rows.map((r) => (
        <li key={r.key} className="grid grid-cols-[minmax(0,9rem)_1fr_3.5rem] sm:grid-cols-[minmax(0,16rem)_1fr_3.5rem] items-center gap-3 text-sm" title={r.title}>
          <span className="truncate">{r.label}</span>
          <span className="h-3 cg-track rounded-r"><span className="bar block h-3 rounded-r" style={{ width: `${(r.value / max) * 100}%` }} /></span>
          <span className="tabular-nums text-right text-gray-700">{r.text}</span>
        </li>
      ))}
    </ul>
  )
}

// ---------------------------------------------------------------- report sections
function Summary({ data }) {
  const r = data.report
  const s = r.summary
  const headline = data.current_semester && s.coverage_now !== null ? s.coverage_now : s.coverage
  return (
    <section className="bg-white border border-gray-200 rounded p-5 print-avoid">
      <p className="text-sm text-gray-600">
        {data.source === 'approved'
          ? `Approved syllabus: ${data.syllabus.college_name}, ${data.department}${data.syllabus.batch ? `, batch ${data.syllabus.batch}` : ''}`
          : `Your uploaded syllabus${data.department ? `: ${data.department}` : ''} (not stored)`}
        {' \u00b7 '}compared with {r.market.jobs} open {r.field === 'computing' ? 'computing ' : ''}jobs in Kolkata
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-x-10 gap-y-4">
        <div>
          <p className="text-6xl font-semibold tabular-nums leading-none">{pct(headline)}</p>
          <p className="mt-2 text-sm text-gray-700 max-w-xs">
            of what these jobs ask for is taught{data.current_semester ? ` by semester ${data.current_semester}` : ' in the whole course'}
            {data.current_semester && s.coverage !== headline ? ` (${pct(s.coverage)} by the end of the course)` : ''}
          </p>
        </div>
        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-8 gap-y-3 text-sm">
          {Object.entries(STATUS).map(([key, st]) => (
            <div key={key}>
              <dt className="flex items-center gap-1.5 text-gray-600"><span className={`w-2.5 h-2.5 rounded-sm ${st.cls}`} aria-hidden="true" />{st.label}</dt>
              <dd className="text-2xl font-semibold tabular-nums">{s[key]}</dd>
            </div>
          ))}
        </dl>
      </div>
      <p className="mt-3 text-xs text-gray-500">
        Out of the {s.skills_checked} skills Kolkata jobs ask for most. {s.foundation_subjects} of {s.subjects} subjects are
        foundation subjects (maths, physics, theory) that job posts don't name; they are not counted as gaps.
      </p>
    </section>
  )
}

function LearnNow({ items }) {
  if (!items.length) return <p className="text-sm text-gray-600">Nothing urgent: the syllabus covers the most-asked skills.</p>
  return (
    <ol className="grid sm:grid-cols-2 gap-3">
      {items.map((x, i) => (
        <li key={x.skill} className="p-3 rounded border border-gray-200 flex gap-3 print-avoid">
          <span className="font-display text-2xl text-gray-400 w-6 shrink-0">{i + 1}</span>
          <div className="min-w-0">
            <p className="font-semibold">{x.skill}</p>
            <p className="text-sm text-gray-700">
              {x.jobs} jobs ({x.share}%) {'\u00b7'} {STATUS[x.status].label.toLowerCase()} {'\u00b7'} {TREND[x.trend]}
            </p>
            {x.coming_in_semester && <p className="text-sm text-hooghly">Comes later in semester {x.coming_in_semester}; start early.</p>}
            <Link to={`/?q=${encodeURIComponent(x.skill)}`} className="text-sm text-dusk underline no-print">See these jobs</Link>
          </div>
        </li>
      ))}
    </ol>
  )
}

function ExtraClasses({ classes }) {
  const list = classes.classes
  if (!list.length) return <p className="text-sm text-gray-600">No extra class needed: no big gap the market clearly asks for.</p>
  return (
    <div className="space-y-5">
      <div>
        <p className="text-sm text-gray-700 mb-2">
          Together these {list.length} classes ({classes.reach.hours} hours) reach <strong>{classes.reach.share}%</strong> of the
          jobs, out of {classes.reach.possible_share}% possible if every gap were closed. Jobs reached after each class:
        </p>
        <Bars rows={list.map((c, i) => ({ key: c.title, label: `${i + 1}. ${c.title}`, value: c.reach_after,
          text: `${c.reach_after}%`, title: `${c.new_jobs} new jobs reached by this class` }))} />
      </div>
      <ol className="grid md:grid-cols-2 gap-4">
        {list.map((c, i) => (
          <li key={c.title} className="p-4 rounded border border-gray-200 print-avoid">
            <p className="font-semibold text-lg">{i + 1}. {c.title}</p>
            <p className="text-sm text-gray-700">{c.hours} hours {'\u00b7'} {c.format}</p>
            <p className="mt-2 text-sm">
              {c.skills.map((s) => `${s.skill} (${s.jobs} jobs)`).join(', ')}
            </p>
            <p className="mt-1 text-sm text-gray-700">Reaches {c.jobs} jobs ({c.share}%), {c.new_jobs} not reached by the classes above.</p>
            {c.together.length > 0 && (
              <p className="mt-1 text-sm text-gray-700">
                Asked together: {c.together.map((t) => `${t.a} + ${t.b} (${t.jobs} jobs, ${t.lift}\u00d7 more often than by chance)`).join('; ')}
              </p>
            )}
            {c.prerequisites.length > 0 && (
              <p className="mt-1 text-sm">
                Needs first: {c.prerequisites.map((p) => `${p.skill} ${p.in_syllabus ? '(in the syllabus \u2713)' : '(not in the syllabus: teach it first)'}`).join(', ')}
              </p>
            )}
            <details className="mt-2 text-sm">
              <summary className="cursor-pointer text-dusk">Free learning material</summary>
              <ul className="mt-1 list-disc pl-5">
                {c.resources.map((r) => <li key={r.url}><a href={r.url} target="_blank" rel="noopener noreferrer" className="text-dusk underline">{r.title}</a></li>)}
              </ul>
            </details>
          </li>
        ))}
      </ol>
    </div>
  )
}

function SubjectsPanel({ report }) {
  const rows = report.subjects.filter((s) => s.kind !== 'lab' && s.jobs > 0).slice(0, 10)
  return (
    <div className="grid lg:grid-cols-2 gap-6">
      <div>
        <h3 className="font-semibold mb-2">Subjects most asked for by jobs</h3>
        {rows.length ? (
          <Bars rows={rows.map((s) => ({ key: `${s.name}-${s.semester}`, label: `${s.name} (Sem ${s.semester ?? '-'})`, value: s.share,
            text: `${s.share}%`, title: `${s.jobs} jobs ask for ${s.skills.join(', ')}` }))} />
        ) : <p className="text-sm text-gray-600">No subject matched a job skill.</p>}
      </div>
      <div>
        <h3 className="font-semibold mb-2">Foundation subjects ({report.foundation_subjects.length})</h3>
        <p className="text-sm text-gray-600 mb-2">Important for exams, GATE and interviews, but job posts don't name them.</p>
        <ul className="flex flex-wrap gap-1.5">
          {report.foundation_subjects.map((s, i) => (
            <li key={`${s.name}-${i}`} className="px-2 py-0.5 rounded-sm bg-paper text-sm text-gray-700">{s.name}</li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function Report({ data, audience, onRerun, electiveChoices, chosen, setChosen }) {
  const r = data.report
  const learn = (
    <Panel key="learn" title={data.current_semester ? 'What to learn now' : 'Biggest gaps'}
           note="Skills Kolkata jobs clearly ask for that the syllabus does not teach properly, biggest gap first.">
      <LearnNow items={r.learn_now} />
    </Panel>
  )
  const classes = (
    <Panel key="classes" title="Extra classes the college could arrange"
           note="Short add-on classes, chosen to reach the most jobs per teaching hour. Skills that jobs ask for together are taught together.">
      <ExtraClasses classes={data.classes} />
    </Panel>
  )
  return (
    <div className="space-y-6">
      <Summary data={data} />
      {electiveChoices.length > 0 && (
        <section className="bg-white border border-gray-200 rounded p-5 no-print">
          <h2 className="font-semibold">Your elective choices</h2>
          <p className="text-sm text-gray-600 mb-2">Tick the electives you took; they then count as taught for you.</p>
          <div className="flex flex-wrap gap-2">
            {electiveChoices.map((c) => (
              <label key={c} className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-gray-300 text-sm">
                <input type="checkbox" checked={chosen.includes(c)}
                       onChange={(e) => setChosen(e.target.checked ? [...chosen, c] : chosen.filter((x) => x !== c))} />{c}
              </label>
            ))}
          </div>
          <button onClick={onRerun} className="mt-3 px-4 py-2 rounded bg-dusk text-white text-sm font-semibold">Update the report</button>
        </section>
      )}
      <Panel title="What jobs ask for, and whether the syllabus teaches it"
             note={`The ${Math.min(15, r.skills.length)} skills asked for most in open ${r.field === 'computing' ? 'computing ' : ''}jobs in Kolkata.`}>
        {r.skills.length ? <DemandChart skills={r.skills} /> : <p className="text-sm text-gray-600">Not enough jobs to compare yet.</p>}
      </Panel>
      {audience === 'faculty' ? [classes, learn] : [learn, classes]}
      <Panel title="How the syllabus builds up, semester by semester"
             note={`Share of job demand covered by the end of each semester.${data.current_semester ? ' Your semester is highlighted.' : ''}`}>
        <SemesterChart semesters={r.semesters} current={data.current_semester} />
      </Panel>
      <Panel title="Subjects and jobs"><SubjectsPanel report={r} /></Panel>
      <details className="bg-white border border-gray-200 rounded p-5 text-sm text-gray-700">
        <summary className="cursor-pointer font-semibold text-ink">How this report is made</summary>
        <ul className="mt-2 list-disc pl-5 space-y-1">
          <li>Each subject is linked to job skills: skills written in its name or topics, a table of common B.Tech subjects, and an AI model (sentence embeddings) for the rest.</li>
          <li>Demand = share of open {r.field === 'computing' ? 'computing ' : ''}jobs in Kolkata that ask for the skill, with a 95% Wilson confidence range.</li>
          <li>Trend compares the last 30 days with the 60 days before (two-proportion test); it says rising or falling only when the change is clear (p &lt; 0.05).</li>
          <li>Extra classes: skills asked for together are found with association rules (Apriori: support, confidence, lift); classes are chosen to reach the most jobs per teaching hour (greedy set cover).</li>
          <li>Jobs from Adzuna are shown in search but never counted here. Updated {new Date(r.market.as_of).toLocaleString('en-IN')}.</li>
        </ul>
      </details>
    </div>
  )
}

// ---------------------------------------------------------------- share the syllabus (login)
function ShareSyllabus({ file, subjects, colleges, defaults }) {
  const { user } = useAuth()
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ college_id: defaults.college_id || '', college_name: '', department: defaults.department || '',
    batch: defaults.batch || '', semester: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [sent, setSent] = useState(null)
  const update = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  if (!user) {
    return (
      <p className="text-sm text-gray-700">
        Want this syllabus used for everyone from your college? <Link to={loginUrl('/syllabus')} className="text-dusk underline">Log in</Link> and
        send it; an admin checks it first.
      </p>
    )
  }
  if (sent) return <p className="text-sm p-3 rounded bg-green-50 text-green-800">{sent}</p>

  async function send(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    const fd = new FormData()
    fd.append('file', file)
    fd.append('department', form.department.trim())
    if (form.college_id && form.college_id !== 'other') fd.append('college_id', form.college_id)
    else fd.append('college_name', form.college_name.trim())
    if (form.batch.trim()) fd.append('batch', form.batch.trim())
    if (form.semester) fd.append('semester', form.semester)
    fd.append('subjects_json', JSON.stringify(cleanSubjects(subjects)))
    try {
      const r = await api('/api/me/syllabi', { method: 'POST', form: fd })
      setSent(r.message)
      toast('Syllabus sent for checking.')
    } catch (err) {
      setError(err.message)
    }
    setBusy(false)
  }

  return open ? (
    <form onSubmit={send} className="grid sm:grid-cols-2 gap-3 text-sm">
      <p className="sm:col-span-2 text-gray-700">
        We keep the file and the subject table so an admin can check them. After approval, everyone who picks your college and
        department sees this syllabus first. You can take it back while it is waiting.
      </p>
      <label className="block">College
        <select required value={form.college_id} onChange={update('college_id')} className={input}>
          <option value="">Choose your college</option>
          {colleges.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          <option value="other">My college is not in the list</option>
        </select>
      </label>
      {form.college_id === 'other' && (
        <label className="block">College full name
          <input required minLength={3} maxLength={200} value={form.college_name} onChange={update('college_name')} className={input} />
        </label>
      )}
      <label className="block">Department
        <input required minLength={2} maxLength={120} value={form.department} onChange={update('department')} placeholder="e.g. CSE (AI & ML)" className={input} />
      </label>
      <label className="block">Batch
        <input maxLength={40} value={form.batch} onChange={update('batch')} placeholder="e.g. 2023-27" className={input} />
      </label>
      <label className="block">Only one semester? (leave empty for the whole course)
        <select value={form.semester} onChange={update('semester')} className={input}>
          <option value="">Whole course</option>
          {SEMESTERS.map((s) => <option key={s} value={s}>Semester {s}</option>)}
        </select>
      </label>
      {error && <p className="sm:col-span-2 p-2 rounded bg-red-50 text-sindoor">{error}</p>}
      <div className="sm:col-span-2 flex gap-2">
        <button disabled={busy} className="px-4 py-2 rounded bg-dusk text-white font-semibold disabled:opacity-50">{busy ? 'Sending' : 'Send for checking'}</button>
        <button type="button" onClick={() => setOpen(false)} className="px-4 py-2 rounded border border-gray-300">Cancel</button>
      </div>
    </form>
  ) : (
    <button onClick={() => setOpen(true)} className="px-4 py-2 rounded border border-gray-300 text-sm hover:border-dusk">
      Send this syllabus so it is used for everyone
    </button>
  )
}

// ---------------------------------------------------------------- the page
export default function CurriculumPage() {
  const toast = useToast()
  const [colleges, setColleges] = useState([])
  const [audience, setAudience] = useState('student')
  const [pick, setPick] = useState({ college_id: '', department: '', semester: '' })
  const [lookup, setLookup] = useState(null)          // { found, syllabus, message }
  const [file, setFile] = useState(null)
  const [read, setRead] = useState(null)              // what the quick check read from the file
  const [subjects, setSubjects] = useState([])
  const [chosen, setChosen] = useState([])
  const [report, setReport] = useState(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const uploadRef = useRef(null)
  const reportRef = useRef(null)

  useEffect(() => { api('/api/syllabus/colleges').then(setColleges).catch(() => {}) }, [])

  const college = colleges.find((c) => c.id === pick.college_id)
  const departments = useMemo(() => [...new Set((college?.syllabi || []).map((s) => s.department))], [college])
  const semester = pick.semester ? Number(pick.semester) : null

  // elective choices: from the uploaded table, or from the report of an approved syllabus
  const electiveChoices = useMemo(() => {
    if (report?.source === 'quick') return [...new Set(subjects.filter((s) => s.is_elective).flatMap((s) => s.options || []).filter(Boolean))]
    if (report) return [...new Set(report.report.skills.flatMap((s) => s.taught_in.filter((t) => t.option).map((t) => t.option)))]
    return []
  }, [report, subjects])

  async function makeReport(body) {
    setBusy('report')
    setError('')
    try {
      const data = await api('/api/syllabus/report', { method: 'POST', body: { ...body, current_semester: semester, chosen } })
      setReport(data)
      setTimeout(() => reportRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
    } catch (err) {
      setError(err.message)
    }
    setBusy('')
  }

  async function find(e) {
    e.preventDefault()
    setBusy('lookup')
    setError('')
    setReport(null)
    setChosen([])
    try {
      const r = await api('/api/syllabus/lookup', { params: { college_id: pick.college_id, department: pick.department.trim(), semester } })
      setLookup(r)
      setBusy('')
      if (r.found) makeReport({ syllabus_id: r.syllabus.id })
    } catch (err) {
      setError(err.message)
      setBusy('')
    }
  }

  async function readFile(e) {
    e.preventDefault()
    if (!file) return
    setBusy('read')
    setError('')
    setReport(null)
    setChosen([])
    const fd = new FormData()
    fd.append('file', file)
    try {
      const r = await api('/api/syllabus/read', { method: 'POST', form: fd })
      setRead(r)
      setSubjects(r.subjects)
      toast(`Read ${r.subjects.length} subjects. Check them, then see your report.`)
    } catch (err) {
      setError(err.message)
    }
    setBusy('')
  }

  const quickReport = () => {
    const clean = cleanSubjects(subjects)
    if (!clean.length) { setError('Add at least one subject.'); return }
    makeReport({ subjects: clean, department: pick.department.trim() || read?.department || null })
  }
  const rerun = () => (report.source === 'approved' ? makeReport({ syllabus_id: report.syllabus.id }) : quickReport())
  const showUpload = () => setTimeout(() => uploadRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 50)

  return (
    <div className="cg cg-print-page max-w-6xl mx-auto px-4 py-8">
      <div className="no-print">
        <p className="text-sm font-semibold text-sindoor">For students and faculty</p>
        <h1 className="font-display text-4xl sm:text-5xl max-w-3xl">Does your syllabus teach what Kolkata jobs ask for?</h1>
        <p className="mt-3 text-gray-700 max-w-2xl">
          Compare a college syllabus with live job posts: see the gaps, what to learn now, and which extra classes would help most.
        </p>
        <div className="mt-5 inline-flex rounded-full border border-gray-300 p-1 bg-white" role="tablist" aria-label="I am">
          {[['student', 'I am a student'], ['faculty', 'I am faculty or HOD']].map(([v, t]) => (
            <button key={v} role="tab" aria-selected={audience === v} onClick={() => setAudience(v)}
                    className={`px-4 py-1.5 rounded-full text-sm ${audience === v ? 'bg-dusk text-white' : 'text-gray-700'}`}>{t}</button>
          ))}
        </div>

        <div className="mt-6 grid lg:grid-cols-2 gap-6">
          <form onSubmit={find} className="bg-white border border-gray-200 rounded p-5 space-y-3">
            <h2 className="font-display text-2xl">1. Find your college's syllabus</h2>
            <label className="block text-sm">College
              <select required value={pick.college_id} onChange={(e) => { setPick({ ...pick, college_id: e.target.value }); setLookup(null) }} className={input}>
                <option value="">Choose your college</option>
                {colleges.map((c) => <option key={c.id} value={c.id}>{c.name}{c.short_name ? ` (${c.short_name})` : ''}</option>)}
              </select>
            </label>
            <label className="block text-sm">Department
              <input required minLength={2} maxLength={120} list="cg-departments" value={pick.department}
                     onChange={(e) => { setPick({ ...pick, department: e.target.value }); setLookup(null) }}
                     placeholder="e.g. CSE (AI & ML)" className={input} />
              <datalist id="cg-departments">{departments.map((d) => <option key={d} value={d} />)}</datalist>
            </label>
            <label className="block text-sm">{audience === 'student' ? 'Your current semester' : 'Semester (optional)'}
              <select value={pick.semester} onChange={(e) => setPick({ ...pick, semester: e.target.value })} className={input}>
                <option value="">{audience === 'student' ? 'Choose' : 'Whole course'}</option>
                {SEMESTERS.map((s) => <option key={s} value={s}>Semester {s}</option>)}
              </select>
            </label>
            <button disabled={busy !== ''} className="px-5 py-2.5 rounded bg-dusk text-white font-semibold disabled:opacity-50">
              {busy === 'lookup' ? 'Looking' : 'Check my syllabus'}
            </button>
            {lookup && (
              <div className={`p-3 rounded text-sm ${lookup.found ? 'bg-green-50 text-green-800' : 'bg-amber-50 text-amber-900'}`} role="status">
                {lookup.message}
                <button type="button" onClick={showUpload} className="block mt-1 underline font-semibold">
                  {lookup.found ? 'Upload your syllabus for a more accurate result' : 'Upload your syllabus'}
                </button>
              </div>
            )}
          </form>

          <form ref={uploadRef} onSubmit={readFile} className="bg-white border border-gray-200 rounded p-5 space-y-3">
            <h2 className="font-display text-2xl">2. Or upload your syllabus</h2>
            <p className="text-sm text-gray-600">PDF or Word, up to 10 MB. A quick check: nothing is stored unless you choose to send it.</p>
            <label className="flex items-center gap-3 p-4 rounded border-2 border-dashed border-gray-300 cursor-pointer hover:border-dusk">
              <Icon name="upload" className="w-6 h-6 text-gray-500" />
              <span className="text-sm">{file ? file.name : 'Choose the syllabus file'}</span>
              <input type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                     className="sr-only" onChange={(e) => { setFile(e.target.files[0] || null); setRead(null) }} />
            </label>
            <button disabled={!file || busy !== ''} className="px-5 py-2.5 rounded bg-dusk text-white font-semibold disabled:opacity-50">
              {busy === 'read' ? 'Reading the syllabus' : 'Read the syllabus'}
            </button>
          </form>
        </div>

        {read && (
          <section className="mt-6 bg-white border border-gray-200 rounded p-5 space-y-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="font-display text-2xl">Check the subjects we read</h2>
              <p className="text-sm text-gray-600">
                {subjects.length} subjects{read.department ? ` \u00b7 ${read.department}` : ''}{read.batch ? ` \u00b7 batch ${read.batch}` : ''}
                {read.method === 'ai' ? ' \u00b7 read with AI, please check carefully' : ''}
              </p>
            </div>
            <details>
              <summary className="cursor-pointer text-sm text-dusk">Show and correct the subject table (optional)</summary>
              <div className="mt-3"><SubjectTable subjects={subjects} onChange={setSubjects} /></div>
            </details>
            <button onClick={quickReport} disabled={busy !== ''} className="px-5 py-2.5 rounded bg-taxi text-ink font-semibold disabled:opacity-50">
              {busy === 'report' ? 'Comparing with live jobs' : 'Show my report'}
            </button>
          </section>
        )}

        {busy === 'report' && <p className="mt-6 text-gray-600" role="status">Comparing with live jobs. The first report can take up to a minute while the AI model wakes up.</p>}
        {error && <p className="mt-6 p-4 rounded bg-red-50 text-sindoor text-sm" role="alert">{error}</p>}
      </div>

      {report && (
        <div ref={reportRef} className="mt-10 scroll-mt-20">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <h2 className="font-display text-3xl">Kolkata Tech Job Market Intelligence &amp; Skill Gap Analyser</h2>
            <button onClick={() => window.print()} className="no-print px-4 py-2 rounded border border-gray-300 text-sm hover:border-dusk">
              Print or save as PDF (for the HOD)
            </button>
          </div>
          <Report data={report} audience={audience} onRerun={rerun} electiveChoices={electiveChoices} chosen={chosen} setChosen={setChosen} />
          {report.source === 'quick' && file && (
            <section className="mt-6 bg-white border border-gray-200 rounded p-5 no-print">
              <ShareSyllabus file={file} subjects={subjects} colleges={colleges}
                             defaults={{ college_id: pick.college_id, department: pick.department || read?.department || '', batch: read?.batch || '' }} />
            </section>
          )}
        </div>
      )}
    </div>
  )
}
