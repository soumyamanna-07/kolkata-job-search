// One job in a results list (a row on a shared sheet). `extra` shows below the job (e.g. CV match reasons),
// `badge` shows on the right (e.g. match score).
import { Link } from 'react-router-dom'
import {
  experienceText, isDirect, JOB_TYPE_LABELS, postedText, salaryText, SOURCE_CREDITS, WORK_MODE_LABELS,
} from '../lib/format'
import Icon from '../lib/icons'
import { SaveButton, ShareButton } from './JobActions'

export function DirectBadge() {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-sm bg-taxi text-ink text-xs font-semibold"
          title="The Apply button opens the employer's own page">
      <Icon name="check" className="w-3.5 h-3.5" /> Direct apply
    </span>
  )
}

export function facts(job) {
  return [
    salaryText(job),
    experienceText(job),
    JOB_TYPE_LABELS[job.job_type],
    WORK_MODE_LABELS[job.work_mode],
  ].filter(Boolean)
}

function initials(name) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase()
}

export default function JobCard({ job, extra, badge, number }) {
  const credit = SOURCE_CREDITS[job.source]
  const hasSalary = job.salary_min || job.salary_max

  return (
    <article className="relative px-4 sm:px-5 py-4 flex gap-4 hover:bg-paper/50">
      <div className="hidden sm:flex shrink-0 w-11 h-11 rounded bg-dusk/10 text-dusk font-semibold items-center justify-center"
           aria-hidden="true">
        {number ?? initials(job.company_name)}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex justify-between gap-3">
          <div className="min-w-0">
            <Link to={`/jobs/${job.id}`}
                  className="font-display text-lg leading-snug text-ink hover:text-dusk hover:underline underline-offset-4">
              {job.title}
            </Link>
            <p className="text-sm text-gray-600 flex flex-wrap items-center gap-x-1">
              <span className="font-medium text-gray-800">{job.company_name}</span>
              {job.posted_by && <span className="text-gray-500">via {job.posted_by}</span>}
              <span className="inline-flex items-center gap-0.5 text-gray-500">
                <Icon name="pin" className="w-3.5 h-3.5" />{job.area}
              </span>
            </p>
          </div>
          {badge || <span className="text-xs text-gray-500 whitespace-nowrap pt-1.5">{postedText(job.posted_at)}</span>}
        </div>

        <p className="mt-2 text-sm flex flex-wrap items-center gap-x-4 gap-y-1">
          {isDirect(job) && <DirectBadge />}
          {facts(job).map((fact, i) => (
            <span key={fact} className={i === 0 && hasSalary ? 'font-semibold text-money' : 'text-gray-600'}>{fact}</span>
          ))}
        </p>

        {job.snippet && <p className="mt-2 text-sm text-gray-600 line-clamp-2 max-w-[72ch]">{job.snippet}</p>}
        {extra}

        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
          {job.skills.length > 0 && (
            <span className="text-xs text-dusk">{job.skills.slice(0, 6).join(', ')}</span>
          )}
          <span className="ml-auto flex items-center -mr-2">
            {credit && (
              <a href={credit.url} target="_blank" rel="noopener noreferrer"
                 className="mr-1 text-xs text-gray-500 hover:underline">{credit.text}</a>
            )}
            <ShareButton job={job} />
            <SaveButton jobId={job.id} />
          </span>
        </div>
      </div>
    </article>
  )
}
