// Match my CV: upload a CV (PDF or Word), see the best-matching jobs and the skills to learn next.
// The CV is read once and not stored.
import { useRef, useState } from 'react'
import JobCard from '../components/JobCard'
import { api } from '../lib/api'
import Icon from '../lib/icons'

function scoreTone(score) {
  if (score >= 75) return 'bg-green-700 text-white'
  if (score >= 60) return 'bg-taxi text-ink'
  return 'bg-gray-200 text-gray-800'
}

export default function MatchPage() {
  const input = useRef(null)
  const [file, setFile] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)

  function pick(f) {
    setError('')
    if (!f) return
    if (!/\.(pdf|docx)$/i.test(f.name)) return setError('Please choose a PDF or Word (.docx) file.')
    if (f.size > 5 * 1024 * 1024) return setError('This file is bigger than 5 MB. Please use a smaller CV.')
    setFile(f)
  }

  async function match(e) {
    e.preventDefault()
    if (!file) return
    setBusy(true)
    setError('')
    const form = new FormData()
    form.append('file', file)
    try {
      setResult(await api('/api/cv/match', { method: 'POST', form, params: { limit: 20 } }))
    } catch (err) {
      setError(err.message)
    }
    setBusy(false)
  }

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <h1 className="font-display text-4xl">Match my CV</h1>
      <p className="mt-1 text-gray-600 max-w-2xl">
        Upload your CV and we rank every current Kolkata job for you, explain each score, and show the
        skills that would open the most jobs. Your CV is read once and not saved.
      </p>

      <form onSubmit={match} className="mt-6 max-w-2xl">
        <label onDragOver={(e) => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)}
               onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files[0]) }}
               className={`flex flex-col items-center justify-center gap-2 rounded border-2 border-dashed p-8 text-center cursor-pointer bg-white ${
                 dragging ? 'border-dusk bg-dusk/5' : 'border-gray-300 hover:border-dusk'}`}>
          <Icon name="upload" className="w-8 h-8 text-dusk" />
          <span className="font-medium">{file ? file.name : 'Drop your CV here or click to choose'}</span>
          <span className="text-sm text-gray-500">PDF or Word (.docx), up to 5 MB</span>
          <input ref={input} type="file" accept=".pdf,.docx" className="sr-only" onChange={(e) => pick(e.target.files[0])} />
        </label>
        {error && <p className="mt-3 text-sm text-sindoor">{error}</p>}
        <button disabled={!file || busy}
                className="mt-4 px-6 py-3 rounded bg-taxi text-ink font-semibold hover:bg-taxi-deep disabled:opacity-50">
          {busy ? 'Reading your CV and ranking jobs' : 'Find my best jobs'}
        </button>
      </form>

      {result && (
        <div className="mt-10 grid lg:grid-cols-[1fr_300px] gap-6 items-start">
          <section>
            <h2 className="font-display text-2xl mb-3">Your top {result.items.length} jobs</h2>
            {result.items.length === 0 ? (
              <p className="p-6 bg-white border border-gray-200 rounded text-gray-700">
                No current jobs match this CV yet. Try again in a few days, or set up a job alert.
              </p>
            ) : (
              <div className="bg-white border border-gray-200 rounded divide-y divide-gray-200">
                {result.items.map((job) => (
                  <JobCard key={job.id} job={job}
                    badge={<span className={`shrink-0 h-fit px-2 py-1 rounded text-sm font-semibold tabular-nums ${scoreTone(job.match_score)}`}
                                 title="Match score out of 100">{job.match_score}% match</span>}
                    extra={
                      <div className="mt-2 text-sm space-y-1">
                        {job.matched_skills.length > 0 && (
                          <p><span className="text-green-800 font-medium">You have:</span> {job.matched_skills.join(', ')}</p>
                        )}
                        {job.missing_skills.length > 0 && (
                          <p><span className="text-sindoor font-medium">To learn:</span> {job.missing_skills.join(', ')}</p>
                        )}
                        {job.reasons.length > 0 && <p className="text-gray-500">{job.reasons.join('. ')}</p>}
                      </div>
                    } />
                ))}
              </div>
            )}
          </section>

          <aside className="space-y-4 lg:sticky lg:top-24">
            <div className="bg-white border border-gray-200 rounded p-5">
              <h2 className="font-display text-xl">What we read from your CV</h2>
              <dl className="mt-2 text-sm space-y-2">
                <div><dt className="text-gray-500">Skills</dt><dd>{result.cv.skills.join(', ') || 'None found'}</dd></div>
                <div><dt className="text-gray-500">Experience</dt>
                  <dd>{result.cv.experience_years != null ? `${result.cv.experience_years} years` : 'Not found (treated as fresher)'}</dd></div>
                {result.cv.education && <div><dt className="text-gray-500">Education</dt><dd>{result.cv.education}</dd></div>}
              </dl>
            </div>
            {result.skill_gap.length > 0 && (
              <div className="bg-dusk text-white rounded p-5">
                <h2 className="font-display text-xl">Skills to learn next</h2>
                <p className="text-sm text-white/75 mb-3">How many of your best-matching jobs ask for each one.</p>
                <ul className="space-y-1.5 text-sm">
                  {result.skill_gap.slice(0, 8).map((g) => (
                    <li key={g.skill} className="flex justify-between gap-3">
                      <span>{g.skill}</span><span className="tabular-nums text-taxi">{g.jobs} jobs</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  )
}
