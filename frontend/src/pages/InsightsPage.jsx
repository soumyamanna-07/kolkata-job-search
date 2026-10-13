// Job market insights: which skills Kolkata employers ask for, where the jobs are, and what they pay.
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { JOB_TYPE_LABELS } from '../lib/format'

const lakh = (v) => (v ? `\u20b9${(v / 100000).toFixed(1)} L` : '-')

// horizontal bars, one series: the bar length is the count, the number is written next to it
function Bars({ rows, labelFor = (v) => v, linkFor }) {
  const max = Math.max(...rows.map((r) => r.count), 1)
  return (
    <ul className="space-y-2">
      {rows.map((r) => {
        const label = labelFor(r.value)
        return (
          <li key={r.value} className="grid grid-cols-[8.5rem_1fr_2.5rem] items-center gap-3 text-sm"
              title={`${label}: ${r.count} jobs`}>
            {linkFor ? <Link to={linkFor(r.value)} className="truncate hover:underline">{label}</Link>
              : <span className="truncate">{label}</span>}
            <span className="h-3 bg-paper rounded-r">
              <span className="bar block h-3 rounded-r" style={{ width: `${(r.count / max) * 100}%` }} />
            </span>
            <span className="tabular-nums text-gray-700 text-right">{r.count}</span>
          </li>
        )
      })}
    </ul>
  )
}

// jobs posted per day: vertical bars, hover a bar to see the date and count
function DailyChart({ days }) {
  const last = days.slice(-60)
  const max = Math.max(...last.map((d) => d.count), 1)
  return (
    <div>
      <div className="flex items-end gap-[2px] h-36 border-b border-gray-300" role="img"
           aria-label={`Jobs posted per day over the last ${last.length} days`}>
        {last.map((d) => (
          <div key={d.value} className="group relative flex-1 h-full flex items-end">
            <div className="bar w-full rounded-t-[3px]"
                 style={{ height: `${Math.max((d.count / max) * 100, 2)}%` }} />
            <span className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block whitespace-nowrap rounded bg-ink text-white text-xs px-2 py-1">
              {new Date(d.value).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}: {d.count}
            </span>
          </div>
        ))}
      </div>
      {last.length > 0 && (
        <div className="flex justify-between text-xs text-gray-500 mt-1">
          <span>{new Date(last[0].value).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}</span>
          <span>{new Date(last[last.length - 1].value).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}</span>
        </div>
      )}
    </div>
  )
}

function Panel({ title, note, children, className = '' }) {
  return (
    <section className={`bg-white border border-gray-200 rounded p-5 ${className}`}>
      <h2 className="font-display text-xl">{title}</h2>
      {note && <p className="text-sm text-gray-600 mb-4">{note}</p>}
      {children}
    </section>
  )
}

export default function InsightsPage() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api('/api/insights').then(setData).catch((e) => setError(e.message))
  }, [])

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <h1 className="font-display text-4xl">Kolkata job market today</h1>
      <p className="mt-1 text-gray-600 max-w-2xl">
        Worked out from every live job on this site. It changes every day as jobs open and close.
      </p>

      {error && <p className="mt-6 p-4 rounded bg-red-50 text-sindoor text-sm">{error}</p>}
      {!data && !error && <p className="mt-6 text-gray-500">Loading the numbers</p>}

      {data && (
        <>
          <div className="mt-6 grid grid-cols-2 md:grid-cols-4 bg-white border border-gray-200 rounded divide-x divide-gray-200">
            {[[data.open_jobs.toLocaleString('en-IN'), 'live jobs'],
              [`${data.fresher_friendly_share}%`, 'open to freshers (0-1 year)'],
              [lakh(data.salary.median), 'middle yearly salary'],
              [`${lakh(data.salary.p25)} - ${lakh(data.salary.p75)}`, 'middle half of salaries']].map(([v, l]) => (
              <div key={l} className="px-4 py-4">
                <p className="font-display text-2xl">{v}</p>
                <p className="text-xs text-gray-600">{l}</p>
              </div>
            ))}
          </div>
          <p className="mt-2 text-xs text-gray-500">
            Salaries come from the {data.salary.jobs_with_salary.toLocaleString('en-IN')} jobs that state one.
          </p>

          <div className="mt-6 grid lg:grid-cols-2 gap-5 items-start">
            <Panel title="Skills employers ask for most" note="Number of live jobs asking for each skill. Click a skill to see its jobs.">
              <Bars rows={data.top_skills.slice(0, 15).map((s) => ({ value: s.skill, count: s.jobs }))}
                    linkFor={(skill) => `/?skills=${encodeURIComponent(skill)}`} />
            </Panel>
            <div className="grid gap-5">
              <Panel title="Jobs posted per day" note="Last 60 days. Point at a bar to see the date.">
                <DailyChart days={data.posted_per_day} />
              </Panel>
              <Panel title="Where the jobs are">
                <Bars rows={data.by_area} linkFor={(area) => `/?area=${encodeURIComponent(area)}`} />
              </Panel>
            </div>
            <Panel title="Companies hiring the most">
              <Bars rows={data.top_companies.slice(0, 10)} />
            </Panel>
            <Panel title="Type of job">
              <Bars rows={data.by_job_type} labelFor={(v) => (v === 'not_stated' ? 'Not stated' : JOB_TYPE_LABELS[v] || v)} />
            </Panel>
          </div>

          <Panel title="Pay by skill" note="Middle yearly salary of jobs asking for the skill, where a salary is given." className="mt-5">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-600 border-b border-gray-200">
                    <th className="py-2 pr-4 font-medium">Skill</th>
                    <th className="py-2 pr-4 font-medium text-right">Jobs</th>
                    <th className="py-2 pr-4 font-medium text-right">Share of all jobs</th>
                    <th className="py-2 pr-4 font-medium text-right">Middle salary</th>
                    <th className="py-2 font-medium text-right">Jobs stating pay</th>
                  </tr>
                </thead>
                <tbody>
                  {data.top_skills.slice(0, 15).map((s) => (
                    <tr key={s.skill} className="border-b border-gray-100">
                      <td className="py-2 pr-4"><Link to={`/?skills=${encodeURIComponent(s.skill)}`} className="text-dusk hover:underline">{s.skill}</Link></td>
                      <td className="py-2 pr-4 text-right tabular-nums">{s.jobs}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{s.share}%</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{lakh(s.salary.median)}</td>
                      <td className="py-2 text-right tabular-nums text-gray-600">{s.salary.jobs_with_salary}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
    </div>
  )
}
