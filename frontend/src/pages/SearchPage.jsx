// Home page: search live Kolkata jobs. Filters live in the URL, so a search can be shared or bookmarked.
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import AlertButton from '../components/AlertButton'
import HowrahBridge, { useSkyPhase } from '../components/HowrahBridge'
import JobCard from '../components/JobCard'
import { api } from '../lib/api'
import { JOB_TYPE_LABELS, WORK_MODE_LABELS } from '../lib/format'
import Icon from '../lib/icons'

const FILTER_KEYS = ['q', 'area', 'job_type', 'work_mode', 'skills', 'experience_years',
  'salary_expected', 'posted_within_days', 'direct_only', 'sort', 'page']
const SALARY_OPTIONS = [
  ['', 'Any salary'], ['200000', '2 LPA or more'], ['300000', '3 LPA or more'], ['500000', '5 LPA or more'],
  ['800000', '8 LPA or more'], ['1200000', '12 LPA or more'],
]
// a job is live for up to 60 days (still listed by its source); people can narrow that down here
const POSTED_OPTIONS = [['', 'All live jobs'], ['1', 'Last 24 hours'], ['3', 'Last 3 days'], ['7', 'Last 7 days'],
  ['15', 'Last 15 days'], ['30', 'Last 30 days'], ['40', 'Last 40 days'], ['50', 'Last 50 days'], ['60', 'Last 60 days']]
const EXPERIENCE_OPTIONS = [['', 'Any'], ['0', 'Fresher'], ['1', '1 year'], ['2', '2 years'], ['3', '3 years'],
  ['5', '5 years'], ['8', '8 years or more']]
const QUICK_SEARCHES = [
  ['Freshers', { experience_years: '0' }], ['Data analyst', { q: 'data analyst' }], ['Sales', { q: 'sales' }],
  ['Accounts', { q: 'accountant' }], ['Teaching', { q: 'teacher' }], ['Internships', { job_type: 'internship' }],
  ['Work from home', { work_mode: 'remote' }],
]
// each tool has its own colour, used for its icon (and its glow) and the line on top of its card
const FEATURES = [
  ['/match', 'file', 'Match my CV', 'Upload your CV and see the jobs that fit you best, with the skills you are missing.',
    'bg-taxi text-ink', 'bg-taxi', 'rgb(244 196 48 / 0.6)'],
  ['/ask', 'spark', 'Ask AI', 'Ask in plain words, like "Python jobs in Salt Lake for freshers".',
    'bg-sindoor text-white', 'bg-sindoor', 'rgb(184 29 36 / 0.5)'],
  ['/insights', 'chart', 'Market insights', 'Which skills Kolkata employers ask for, and what they pay.',
    'bg-hooghly text-white', 'bg-hooghly', 'rgb(14 124 123 / 0.5)'],
  ['/share-job', 'link', 'Share a job', 'Seen a Kolkata job or campus drive? Share the link for everyone.',
    'bg-dusk text-taxi', 'bg-dusk', 'rgb(23 50 74 / 0.55)'],
]
// "Find work in Kolkata" in Bengali
const BENGALI_LINE = '\u0995\u09b2\u0995\u09be\u09a4\u09be\u09af\u09bc \u0995\u09be\u099c \u0996\u09c1\u0981\u099c\u09c1\u09a8'

function Select({ label, value, onChange, options }) {
  return (
    <label className="block">
      <span className="block text-sm text-gray-600 mb-1">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}
              className="w-full rounded-lg border border-gray-300 bg-white px-2.5 py-2 text-sm">
        {options.map(([v, text]) => <option key={v} value={v}>{text}</option>)}
      </select>
    </label>
  )
}

function Stat({ value, label, tone = 'text-ink', live = false }) {
  return (
    <div className="px-4 sm:px-6 py-4">
      <p className={`stat-number font-display text-3xl sm:text-4xl leading-none ${tone}`}>{value}</p>
      <p className="mt-1.5 text-xs sm:text-sm text-gray-600 flex items-center gap-2">
        {live && <span className="live-dot shrink-0" aria-hidden="true" />}{label}
      </p>
    </div>
  )
}

export default function SearchPage() {
  const [params, setParams] = useSearchParams()
  const get = (key) => params.get(key) || ''
  const [text, setText] = useState(get('q'))
  const [facets, setFacets] = useState(null)
  const [market, setMarket] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [showFilters, setShowFilters] = useState(false)          // phones: filters are folded away

  // change filters; any change except paging goes back to page 1
  function setFilters(changes) {
    const next = new URLSearchParams(params)
    Object.entries(changes).forEach(([key, value]) => (value ? next.set(key, value) : next.delete(key)))
    if (!('page' in changes)) next.delete('page')
    setParams(next)
  }
  const setFilter = (key, value) => setFilters({ [key]: value })

  function toggleSkill(skill) {
    const current = get('skills').split(',').filter(Boolean)
    const next = current.includes(skill) ? current.filter((s) => s !== skill) : [...current, skill]
    setFilter('skills', next.join(','))
  }

  function quickSearch(changes) {
    setText(changes.q || '')
    setParams(new URLSearchParams(changes))
    document.getElementById('results')?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    api('/api/jobs/filters').then(setFacets).catch(() => {})
    api('/api/insights').then(setMarket).catch(() => {})
  }, [])

  const query = params.toString()
  useEffect(() => {
    const current = new URLSearchParams(query)
    const search = Object.fromEntries(FILTER_KEYS.map((k) => [k, current.get(k)]))
    setLoading(true)
    setError('')
    api('/api/jobs', { params: { ...search, page_size: 20 } })
      .then(setResult)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [query])

  const chosenSkills = get('skills').split(',').filter(Boolean)
  const page = Number(get('page') || 1)
  const activeFilters = FILTER_KEYS.filter((k) => !['q', 'sort', 'page'].includes(k) && params.get(k)).length
  const weekAgo = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10)
  const newThisWeek = market?.posted_per_day.filter((d) => d.value >= weekAgo).reduce((sum, d) => sum + d.count, 0)
  const searching = query !== ''
  const phase = useSkyPhase()

  function goToPage(n) {
    setFilter('page', String(n))
    document.getElementById('results')?.scrollIntoView({ behavior: 'smooth' })
  }

  return (
    <div>
      <section className={`relative text-white overflow-hidden ${phase === 'night' ? 'sky-night' : 'sky-day'}`}>
        <div className="relative z-10 max-w-6xl mx-auto px-4 pt-12 sm:pt-20 pb-52 sm:pb-80">
          <h1 className="hero-title font-display text-5xl sm:text-7xl leading-[1.02] max-w-3xl">Find work in Kolkata</h1>
          <p lang="bn" className="font-display text-2xl sm:text-3xl text-taxi mt-3">{BENGALI_LINE}</p>
          <p className="mt-5 max-w-xl text-white/85 sm:text-lg leading-relaxed">
            Every live job from Salt Lake to Howrah in one place: company career pages, job sites,
            recruiters and campus drives, checked every day.
          </p>
          <form className="glass search-glow mt-8 flex max-w-2xl rounded-2xl p-1.5 sm:p-2 transition-shadow"
                onSubmit={(e) => { e.preventDefault(); setFilter('q', text.trim()); document.getElementById('results')?.scrollIntoView({ behavior: 'smooth' }) }}>
            <label htmlFor="q" className="sr-only">Search jobs</label>
            <span className="hidden sm:flex items-center pl-4 rounded-l-xl bg-white text-gray-400"><Icon name="search" /></span>
            <input id="q" value={text} onChange={(e) => setText(e.target.value)} maxLength={200}
                   placeholder="Job title, skill or company"
                   className="flex-1 min-w-0 px-4 py-3.5 sm:py-4 text-ink bg-white rounded-l-xl sm:rounded-l-none focus:outline-none" />
            <button className="btn-taxi px-5 sm:px-8 rounded-r-xl font-semibold">Search</button>
          </form>
          <div className="mt-4 flex flex-wrap gap-2 max-w-2xl">
            {QUICK_SEARCHES.map(([label, changes]) => (
              <button key={label} type="button" onClick={() => quickSearch(changes)}
                      className="glass px-3.5 py-1.5 rounded-full text-sm text-white/95 hover:bg-white/25 transition-colors">
                {label}
              </button>
            ))}
          </div>
        </div>
        <HowrahBridge phase={phase} className="absolute bottom-0 left-0 w-full h-52 sm:h-72" />
      </section>
      <div className="laal-paar" />

      {market && (
        <div className="bg-white border-b border-gray-200 card-raised">
          <div className="max-w-6xl mx-auto px-0 sm:px-4 grid grid-cols-2 md:grid-cols-4 divide-x divide-gray-200">
            <Stat value={market.open_jobs.toLocaleString('en-IN')} label="live jobs in Kolkata" live />
            <Stat value={(newThisWeek || 0).toLocaleString('en-IN')} label="new in the last 7 days" tone="text-hooghly" />
            <Stat value={market.fresher_friendly_jobs.toLocaleString('en-IN')} label="open to freshers (0-1 year)"
                  tone="text-sindoor" />
            <Stat value={market.salary.median ? `\u20b9${(market.salary.median / 100000).toFixed(1)} L` : 'Not enough data'}
                  label="middle yearly salary, where shown" tone="text-money" />
          </div>
        </div>
      )}

      {!searching && (
        <section className="max-w-6xl mx-auto px-4 pt-10" aria-label="Tools">
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {FEATURES.map(([to, icon, title, body, iconTone, topLine, glow]) => (
              <Link key={to} to={to}
                    className="group relative overflow-hidden bg-white border border-gray-200 rounded-2xl p-5 pt-6 card-raised card-lift">
                <span className={`absolute inset-x-0 top-0 h-1 ${topLine}`} aria-hidden="true" />
                <span className={`icon-glow inline-flex w-11 h-11 rounded-xl ${iconTone} items-center justify-center`}
                      style={{ '--glow': glow }}>
                  <Icon name={icon} />
                </span>
                <h2 className="mt-3 font-display text-xl group-hover:text-dusk">{title}</h2>
                <p className="mt-1 text-sm text-gray-600">{body}</p>
              </Link>
            ))}
          </div>
        </section>
      )}

      <div id="results" className="max-w-6xl mx-auto px-4 py-8 grid md:grid-cols-[250px_1fr] gap-8 scroll-mt-20">
        <aside>
          <button type="button" onClick={() => setShowFilters(!showFilters)}
                  className="md:hidden w-full px-3 py-2.5 rounded-xl border border-gray-300 bg-white text-sm text-left">
            {showFilters ? 'Hide filters' : `Show filters${activeFilters ? ` (${activeFilters} on)` : ''}`}
          </button>
          <div className={`${showFilters ? 'block' : 'hidden'} md:block space-y-4 mt-3 md:mt-0 md:sticky md:top-24`}>
            <label className="flex items-start gap-2 p-3 rounded-xl bg-white border border-gray-200 card-raised cursor-pointer">
              <input type="checkbox" className="mt-1 accent-dusk" checked={get('direct_only') === 'true'}
                     onChange={(e) => setFilter('direct_only', e.target.checked ? 'true' : '')} />
              <span className="text-sm">
                <span className="font-semibold">Direct apply only</span>
                <span className="block text-gray-600">Apply on the employer's own page</span>
              </span>
            </label>
            <Select label="Area" value={get('area')} onChange={(v) => setFilter('area', v)}
                    options={[['', 'All of Kolkata'],
                      ...(facets?.areas || []).map((a) => [a.value, `${a.value} (${a.count})`])]} />
            <Select label="Your experience" value={get('experience_years')}
                    onChange={(v) => setFilter('experience_years', v)} options={EXPERIENCE_OPTIONS} />
            <Select label="Salary you expect (yearly)" value={get('salary_expected')}
                    onChange={(v) => setFilter('salary_expected', v)} options={SALARY_OPTIONS} />
            <Select label="Job type" value={get('job_type')} onChange={(v) => setFilter('job_type', v)}
                    options={[['', 'Any type'], ...Object.entries(JOB_TYPE_LABELS)]} />
            <Select label="Work mode" value={get('work_mode')} onChange={(v) => setFilter('work_mode', v)}
                    options={[['', 'Any'], ...Object.entries(WORK_MODE_LABELS)]} />
            <Select label="Posted" value={get('posted_within_days')}
                    onChange={(v) => setFilter('posted_within_days', v)} options={POSTED_OPTIONS} />

            {facets?.skills?.length > 0 && (
              <fieldset>
                <legend className="text-sm text-gray-600 mb-1">Skills most asked for</legend>
                <div className="flex flex-wrap gap-1.5">
                  {facets.skills.slice(0, 18).map((s) => {
                    const on = chosenSkills.includes(s.value)
                    return (
                      <button key={s.value} type="button" onClick={() => toggleSkill(s.value)} aria-pressed={on}
                              className={`px-2.5 py-1 rounded-full text-xs border ${on
                                ? 'bg-dusk border-dusk text-white'
                                : 'bg-white border-gray-300 text-gray-700 hover:border-dusk'}`}>
                        {s.value}
                      </button>
                    )
                  })}
                </div>
              </fieldset>
            )}
            {(activeFilters > 0 || get('q')) && (
              <button onClick={() => { setText(''); setParams({}) }} className="text-sm text-sindoor hover:underline">
                Clear search and filters
              </button>
            )}
          </div>
        </aside>

        <section aria-live="polite">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
            <h2 className="font-display text-2xl">
              {loading && !result ? 'Searching' : result
                ? `${result.total.toLocaleString('en-IN')} job${result.total === 1 ? '' : 's'}${get('q') ? ` for "${get('q')}"` : ''}`
                : 'Jobs'}
            </h2>
            <div className="flex items-center gap-3">
              <AlertButton params={params} />
              <label className="text-sm text-gray-600 whitespace-nowrap">
                <span className="sr-only sm:not-sr-only">Sort by </span>
                <select value={get('sort') || 'relevance'} onChange={(e) => setFilter('sort', e.target.value)}
                        className="ml-1 rounded-lg border border-gray-300 bg-white px-2.5 py-2 text-ink">
                  <option value="relevance">Best match</option>
                  <option value="newest">Newest</option>
                  <option value="salary">Highest salary</option>
                </select>
              </label>
            </div>
          </div>

          {error && <p className="p-4 rounded bg-red-50 text-sindoor text-sm">{error}</p>}
          {!error && result && result.items.length === 0 && !loading && (
            <div className="p-8 bg-white border border-gray-200 rounded-2xl card-raised text-gray-700">
              No live jobs match this search. Remove a filter or try a broader word, like "sales" or "teacher".
            </div>
          )}
          {result?.items.length > 0 && (
            <div className={`bg-white border border-gray-200 rounded-2xl overflow-hidden card-raised divide-y divide-gray-200 ${loading ? 'opacity-50' : ''}`}>
              {result.items.map((job) => <JobCard key={job.id} job={job} />)}
            </div>
          )}

          {result && result.pages > 1 && (
            <nav className="flex items-center justify-center gap-4 mt-6 text-sm" aria-label="Pages">
              <button disabled={page <= 1} onClick={() => goToPage(page - 1)}
                      className="px-4 py-2 rounded-full border border-gray-300 bg-white hover:border-dusk disabled:opacity-40">Previous</button>
              <span>Page {page} of {result.pages}</span>
              <button disabled={page >= result.pages} onClick={() => goToPage(page + 1)}
                      className="px-4 py-2 rounded-full border border-gray-300 bg-white hover:border-dusk disabled:opacity-40">Next</button>
            </nav>
          )}
        </section>
      </div>
    </div>
  )
}
