// Recruiter: post a new job, or edit a post that is waiting for review or was rejected.
// Every post gets an automatic spam check and is approved by an admin before it goes live.
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import EmployerTabs from '../components/EmployerTabs'
import { api } from '../lib/api'
import { JOB_TYPE_LABELS, WORK_MODE_LABELS } from '../lib/format'
import Icon from '../lib/icons'
import { useToast } from '../lib/toast'

const AREAS = ['Kolkata', 'Salt Lake', 'New Town', 'Howrah']
const EMPTY = { title: '', description: '', hiring_for: '', skills: '', area: 'Kolkata', location: '', apply_url: '',
  salary_min: '', salary_max: '', experience_min: '', experience_max: '', job_type: 'full_time', work_mode: 'onsite' }

const lakhToRupees = (v) => (v === '' ? null : Math.round(parseFloat(v) * 100000))
const rupeesToLakh = (v) => (v == null ? '' : String(+(v / 100000).toFixed(2)))
const years = (v) => (v === '' ? null : parseFloat(v))

// server job post -> form fields (salary shown in lakhs a year)
function toForm(job) {
  return {
    ...EMPTY,
    ...Object.fromEntries(Object.keys(EMPTY).map((k) => [k, job[k] ?? EMPTY[k]])),
    skills: (job.skills || []).join(', '),
    salary_min: rupeesToLakh(job.salary_min),
    salary_max: rupeesToLakh(job.salary_max),
    experience_min: job.experience_min ?? '',
    experience_max: job.experience_max ?? '',
  }
}

// form fields -> what the API expects
function toBody(form, agency) {
  return {
    title: form.title.trim(),
    description: form.description.trim(),
    hiring_for: agency ? form.hiring_for.trim() || null : null,
    skills: form.skills.split(',').map((s) => s.trim()).filter(Boolean).slice(0, 30),
    area: form.area,
    location: form.location.trim() || null,
    apply_url: form.apply_url.trim(),
    salary_min: lakhToRupees(form.salary_min),
    salary_max: lakhToRupees(form.salary_max),
    experience_min: years(form.experience_min),
    experience_max: years(form.experience_max),
    job_type: form.job_type || null,
    work_mode: form.work_mode || null,
  }
}

function Notice({ title, text, to, button }) {
  return (
    <div className="bg-white border border-gray-200 rounded p-6 max-w-xl">
      <p className="font-display text-2xl">{title}</p>
      <p className="mt-2 text-gray-600">{text}</p>
      {to && <Link to={to} className="inline-block mt-4 px-5 py-2 rounded bg-dusk text-white font-semibold">{button}</Link>}
    </div>
  )
}

export default function EmployerPostPage() {
  const { id } = useParams()                       // set when editing an existing post
  const navigate = useNavigate()
  const toast = useToast()
  const [company, setCompany] = useState(undefined)  // undefined = loading, null = no details yet
  const [form, setForm] = useState(EMPTY)
  const [loadError, setLoadError] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(null)

  useEffect(() => {
    api('/api/employer/profile').then(setCompany).catch((err) => {
      if (err.status === 404) setCompany(null)
      else setLoadError(err.message)
    })
    if (id) api(`/api/employer/jobs/${id}`).then((job) => setForm(toForm(job))).catch((err) => setLoadError(err.message))
  }, [id])

  const update = (key) => (e) => setForm({ ...form, [key]: e.target.value })
  const agency = company?.account_kind === 'agency'

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const body = toBody(form, agency)
      if (id) {
        await api(`/api/employer/jobs/${id}`, { method: 'PUT', body })
        toast('Changes saved. The post is back in the review queue.')
        navigate('/employer/jobs')
      } else {
        const job = await api('/api/employer/jobs', { method: 'POST', body })
        setSent(job)
        setForm(EMPTY)
        window.scrollTo({ top: 0, behavior: 'smooth' })
      }
    } catch (err) {
      setError(err.message)
    }
    setBusy(false)
  }

  const input = 'mt-1 w-full rounded border border-gray-300 px-3 py-2'
  let body
  if (loadError) body = <p className="p-4 rounded bg-red-50 text-sindoor text-sm">{loadError}</p>
  else if (company === undefined) body = <p className="text-gray-500">Loading</p>
  else if (company === null) {
    body = <Notice title="Add your company first" to="/employer" button="Add company details"
                   text="Before you can post jobs, tell us about your company. An admin approves it, usually within a day." />
  } else if (company.verification_status !== 'approved') {
    body = <Notice title="Your company is not approved yet" to="/employer" button="See company status"
                   text="You can post jobs once an admin approves your company details." />
  } else if (sent) {
    body = (
      <div className="bg-white border border-gray-200 rounded overflow-hidden max-w-xl">
        <div className="laal-paar" />
        <div className="p-6">
          <p className="inline-flex items-center gap-2 font-display text-2xl">
            <Icon name="check" className="w-6 h-6 text-money" /> Sent for review
          </p>
          <p className="mt-2 text-gray-600">
            "{sent.title}" is checked automatically and then by an admin. It goes live on the site once approved,
            and you can follow it under My jobs.
          </p>
          <button onClick={() => setSent(null)} className="mt-4 px-5 py-2 rounded bg-dusk text-white font-semibold">
            Post another job
          </button>
        </div>
      </div>
    )
  } else {
    body = (
      <form onSubmit={submit} className="grid md:grid-cols-[1fr_280px] gap-8 items-start">
        <div className="bg-white border border-gray-200 rounded p-5 space-y-4">
          <h2 className="font-display text-2xl">{id ? 'Edit job post' : 'New job post'}</h2>
          <label className="block text-sm">Job title
            <input required minLength={3} maxLength={120} placeholder="e.g. Junior Accountant" value={form.title}
                   onChange={update('title')} className={input} />
          </label>
          {agency && (
            <label className="block text-sm">Company the job is at (your client)
              <input required minLength={2} maxLength={120} value={form.hiring_for} onChange={update('hiring_for')}
                     className={input} />
              <span className="block mt-1 text-xs text-gray-500">The job is shown under this company, "via {company.company_name}".</span>
            </label>
          )}
          <label className="block text-sm">Job description
            <textarea required minLength={50} maxLength={8000} rows={9} value={form.description}
                      onChange={update('description')} className={input}
                      placeholder={'What the person will do, who you are looking for, working hours, how to apply.\nUse "- " at the start of a line for a list.'} />
            <span className={`block mt-1 text-xs ${form.description.trim().length < 50 ? 'text-sindoor' : 'text-gray-500'}`}>
              {form.description.trim().length} characters (at least 50)
            </span>
          </label>
          <label className="block text-sm">Skills (separated by commas)
            <input maxLength={600} placeholder="e.g. Tally, GST, Excel" value={form.skills} onChange={update('skills')}
                   className={input} />
            <span className="block mt-1 text-xs text-gray-500">Skills named in the description are also found automatically.</span>
          </label>
          <div className="grid sm:grid-cols-2 gap-4">
            <label className="block text-sm">Area
              <select value={form.area} onChange={update('area')} className={input}>
                {AREAS.map((a) => <option key={a}>{a}</option>)}
              </select>
            </label>
            <label className="block text-sm">Office address (optional)
              <input maxLength={120} placeholder="e.g. Sector V, Salt Lake" value={form.location} onChange={update('location')}
                     className={input} />
            </label>
            <label className="block text-sm">Job type
              <select value={form.job_type} onChange={update('job_type')} className={input}>
                {Object.entries(JOB_TYPE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
            <label className="block text-sm">Work mode
              <select value={form.work_mode} onChange={update('work_mode')} className={input}>
                {Object.entries(WORK_MODE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
          </div>
          <fieldset className="grid sm:grid-cols-2 gap-4">
            <legend className="text-sm mb-1">Salary, in lakh rupees a year (optional, but posts with a salary get more applies)</legend>
            <label className="block text-sm">From
              <input type="number" min="0" max="1000" step="0.1" placeholder="e.g. 2.4" value={form.salary_min}
                     onChange={update('salary_min')} className={input} />
            </label>
            <label className="block text-sm">To
              <input type="number" min="0" max="1000" step="0.1" placeholder="e.g. 3.6" value={form.salary_max}
                     onChange={update('salary_max')} className={input} />
            </label>
          </fieldset>
          <fieldset className="grid sm:grid-cols-2 gap-4">
            <legend className="text-sm mb-1">Experience needed, in years (use 0 for freshers)</legend>
            <label className="block text-sm">From
              <input type="number" min="0" max="50" step="0.5" value={form.experience_min}
                     onChange={update('experience_min')} className={input} />
            </label>
            <label className="block text-sm">To
              <input type="number" min="0" max="50" step="0.5" value={form.experience_max}
                     onChange={update('experience_max')} className={input} />
            </label>
          </fieldset>
          <label className="block text-sm">Apply link
            <input required type="url" maxLength={500} placeholder="https://yourcompany.com/careers/accountant"
                   value={form.apply_url} onChange={update('apply_url')} className={input} />
            <span className="block mt-1 text-xs text-gray-500">
              Your careers page, application form or job board page. Candidates go here when they click Apply.
            </span>
          </label>
          {error && <p className="p-3 rounded bg-red-50 text-sindoor text-sm">{error}</p>}
          <div className="flex flex-wrap gap-3">
            <button disabled={busy} className="px-6 py-2.5 rounded bg-dusk text-white font-semibold disabled:opacity-50">
              {busy ? 'Sending' : id ? 'Save and send for review' : 'Send for review'}
            </button>
            {id && <Link to="/employer/jobs" className="px-4 py-2.5 rounded border border-gray-300">Cancel</Link>}
          </div>
        </div>

        <aside className="bg-white border border-gray-200 rounded p-5 text-sm text-gray-600 space-y-3">
          <h2 className="font-display text-xl text-ink">Before you post</h2>
          <p>Each post is checked automatically for signs of a scam, then reviewed by an admin.</p>
          <ul className="list-disc pl-5 space-y-1">
            <li>Never ask candidates for any fee or deposit.</li>
            <li>Use an apply link on your own website or a known job board.</li>
            <li>Give the real salary and experience needed.</li>
            <li>Only Kolkata, Salt Lake, New Town and Howrah jobs.</li>
          </ul>
          <p>You can post up to 20 jobs a day. A live job cannot be edited: close it and post it again.</p>
        </aside>
      </form>
    )
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <EmployerTabs />
      {body}
    </div>
  )
}
