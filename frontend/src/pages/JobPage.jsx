// One job with its full description, Apply, Save, Share and Report.
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ReportButton, SaveButton, ShareButton } from '../components/JobActions'
import { DirectBadge, facts } from '../components/JobCard'
import { api, trackEvent } from '../lib/api'
import { isDirect, postedText, SOURCE_CREDITS } from '../lib/format'
import Icon from '../lib/icons'

export default function JobPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [job, setJob] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    setJob(null)
    setError('')
    api(`/api/jobs/${id}`)
      .then((data) => {
        setJob(data)
        document.title = `${data.title} at ${data.company_name} - Kolkata Live Jobs`
        trackEvent(id, 'view', { source_page: 'job_page' })
      })
      .catch((e) => setError(e.status === 404 || e.status === 422 ? 'This job is not in our list.' : e.message))
    return () => { document.title = 'Kolkata Live Job Search' }
  }, [id])

  if (error) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-10">
        <p className="text-gray-700">{error}</p>
        <Link to="/" className="inline-block mt-3 text-dusk underline">See all current jobs</Link>
      </div>
    )
  }
  if (!job) return <p className="max-w-3xl mx-auto px-4 py-10 text-gray-500">Loading the job</p>

  const closed = job.status !== 'open'
  const credit = SOURCE_CREDITS[job.source]
  const direct = isDirect(job)
  const posted = postedText(job.posted_at)

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      <button onClick={() => navigate(-1)} className="text-sm text-dusk hover:underline">Back to results</button>

      <div className="mt-3 grid lg:grid-cols-[1fr_300px] gap-6 items-start">
        <article className="bg-white border border-gray-200 rounded overflow-hidden">
          <div className="laal-paar" />
          <div className="p-6 sm:p-8">
            {closed && (
              <p className="mb-4 p-3 rounded bg-amber-50 text-amber-900 text-sm">
                This job has closed. The employer is no longer taking applications.
              </p>
            )}
            <h1 className="font-display text-3xl sm:text-4xl leading-tight">{job.title}</h1>
            <p className="mt-2 text-gray-800 font-medium">
              {job.company_name}
              {job.posted_by && <span className="text-gray-500 font-normal">, posted by {job.posted_by}</span>}
            </p>
            <p className="mt-1 text-sm text-gray-500 flex flex-wrap gap-x-4">
              <span className="inline-flex items-center gap-1"><Icon name="pin" className="w-4 h-4" />{job.location_raw || job.area}</span>
              {posted && <span className="inline-flex items-center gap-1"><Icon name="clock" className="w-4 h-4" />Posted {posted.toLowerCase()}</span>}
            </p>

            <p className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
              {direct && <DirectBadge />}
              {facts(job).map((fact, i) => (
                <span key={fact} className={i === 0 && (job.salary_min || job.salary_max) ? 'font-semibold text-money' : 'text-gray-800'}>{fact}</span>
              ))}
            </p>

            <div className="mt-4 flex flex-wrap items-center gap-1 -ml-2.5 border-y border-gray-100 py-1">
              <SaveButton jobId={job.id} withText />
              <ShareButton job={job} withText />
              <ReportButton jobId={job.id} />
            </div>

            {job.skills.length > 0 && (
              <section className="mt-6">
                <h2 className="font-display text-xl mb-2">Skills asked for</h2>
                <ul className="flex flex-wrap gap-1.5">
                  {job.skills.map((s) => (
                    <li key={s}>
                      <Link to={`/?skills=${encodeURIComponent(s)}`}
                            className="inline-block px-2 py-0.5 rounded-sm bg-paper border border-gray-200 text-sm hover:border-dusk">
                        {s}
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <section className="mt-8">
              <h2 className="font-display text-xl mb-2">About the job</h2>
              <div className="text-[15px] text-gray-800 whitespace-pre-line leading-relaxed max-w-[70ch]">
                {job.description || job.snippet || 'The employer did not add a description. Open their page for details.'}
              </div>
            </section>
          </div>
        </article>

        <aside className="lg:sticky lg:top-24 space-y-4">
          {!closed && (
            <div className="bg-white border border-gray-200 rounded p-5">
              <a href={job.apply_url} target="_blank" rel="noopener noreferrer nofollow"
                 onClick={() => trackEvent(job.id, 'click_apply', { source_page: 'job_page' })}
                 className="flex items-center justify-center gap-2 w-full px-6 py-3 rounded bg-taxi text-ink font-semibold hover:bg-taxi-deep">
                {direct ? 'Apply on company site' : `Apply on ${credit.name}`}
                <Icon name="external" className="w-4 h-4" />
              </a>
              <p className="mt-3 text-xs text-gray-500">
                {direct
                  ? 'Opens the employer\'s own job page.'
                  : <>Opens the job on {credit.name}, which links to the employer. <a href={credit.url} target="_blank" rel="noopener noreferrer" className="underline">{credit.text}</a></>}
              </p>
            </div>
          )}
          <div className="bg-dusk text-white rounded p-5">
            <p className="font-display text-lg">Is this job right for you?</p>
            <p className="mt-1 text-sm text-white/80">Upload your CV to see your match score and the skills to learn.</p>
            <Link to="/match" className="mt-3 inline-flex items-center gap-2 text-sm font-semibold text-taxi hover:underline">
              <Icon name="file" className="w-4 h-4" /> Match my CV
            </Link>
          </div>
          <p className="text-xs text-gray-500 px-1">
            Never pay money to get a job. If this job asks for a fee, please report it.
          </p>
        </aside>
      </div>
    </div>
  )
}
