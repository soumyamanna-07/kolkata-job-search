// Ask AI: a chat about jobs and careers, with follow-up questions. Facts about live jobs come from real
// job posts on the site (shown under each answer); career advice comes from the AI's general knowledge.
import { Fragment, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import JobCard from '../components/JobCard'
import { api } from '../lib/api'
import Icon from '../lib/icons'

const EXAMPLES = [
  'Which Python jobs in Salt Lake accept freshers?',
  'How do I prepare for a data analyst interview?',
  'What skills should a B.Tech fresher learn to get a job in Kolkata?',
  'Which companies are hiring accountants right now?',
  'How much does a sales executive earn in Kolkata?',
]

// "**bold**" and job numbers like [2] or [1, 3] inside one line of the answer
function Inline({ text, jobs }) {
  const parts = text.split(/(\*\*[^*]+\*\*|\[\d+(?:\s*,\s*\d+)*\])/g)
  return parts.map((part, i) => {
    if (/^\*\*[^*]+\*\*$/.test(part)) return <strong key={i}>{part.slice(2, -2)}</strong>
    const refs = part.match(/^\[(\d+(?:\s*,\s*\d+)*)\]$/)
    if (refs) {
      return (
        <span key={i}>
          {refs[1].split(',').map((n) => Number(n.trim())).map((n, k) => {
            const job = jobs.find((j) => j.number === n)
            return job ? (
              <Link key={k} to={`/jobs/${job.id}`} title={`${job.title} at ${job.company_name}`}
                    className="inline-block mx-0.5 px-1.5 rounded-sm bg-taxi text-ink text-xs font-semibold align-middle hover:bg-taxi-deep">
                {n}
              </Link>
            ) : <Fragment key={k}>[{n}]</Fragment>
          })}
        </span>
      )
    }
    return <Fragment key={i}>{part}</Fragment>
  })
}

// the AI writes short paragraphs and "- " bullet lists; show them as such
function Answer({ text, jobs }) {
  const blocks = []
  text.split('\n').forEach((raw) => {
    const line = raw.trim()
    if (!line) return
    const bullet = line.match(/^(?:[-*\u2022]|\d+[.)])\s+(.*)$/)
    const heading = line.match(/^#{1,4}\s+(.*)$/)
    if (bullet) {
      const last = blocks[blocks.length - 1]
      if (last && last.type === 'list') last.items.push(bullet[1])
      else blocks.push({ type: 'list', items: [bullet[1]] })
    } else if (heading) blocks.push({ type: 'heading', text: heading[1] })
    else blocks.push({ type: 'para', text: line })
  })
  return (
    <div className="space-y-3 leading-relaxed text-[15px]">
      {blocks.map((b, i) => {
        if (b.type === 'list') {
          return (
            <ul key={i} className="list-disc pl-5 space-y-1">
              {b.items.map((item, k) => <li key={k}><Inline text={item} jobs={jobs} /></li>)}
            </ul>
          )
        }
        if (b.type === 'heading') return <p key={i} className="font-semibold"><Inline text={b.text} jobs={jobs} /></p>
        return <p key={i}><Inline text={b.text} jobs={jobs} /></p>
      })}
    </div>
  )
}

function Reply({ item }) {
  const { question, result } = item
  // with an AI answer, show the jobs it talks about; without one, show the closest jobs
  const shown = result.ai_written ? result.sources.filter((s) => s.cited) : result.sources
  return (
    <article className="space-y-4">
      <div className="flex justify-end">
        <p className="max-w-[85%] px-4 py-2.5 rounded-lg rounded-br-sm bg-dusk text-white text-[15px]">{question}</p>
      </div>
      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <div className="laal-paar" />
        <div className="p-5 sm:p-6">
          <p className="mb-3 inline-flex items-center gap-2 text-sm font-semibold text-sindoor">
            <Icon name="spark" className="w-4 h-4" /> {result.ai_written ? 'AI answer' : 'Matching jobs'}
          </p>
          <Answer text={result.answer} jobs={result.sources} />
          {result.note && <p className="mt-4 text-sm text-gray-500">{result.note}</p>}
          {result.ai_written && (
            <p className="mt-4 text-xs text-gray-500">
              Job facts come only from live posts on this site (yellow numbers open them). Advice is general:
              check details on the job page before applying.
            </p>
          )}
        </div>
      </div>
      {shown.length > 0 && (
        <div>
          <h2 className="font-display text-xl mb-2">{result.ai_written ? 'Jobs in this answer' : 'Closest live jobs'}</h2>
          <div className="bg-white border border-gray-200 rounded divide-y divide-gray-200">
            {shown.map((job) => <JobCard key={job.id} job={job} number={job.number} />)}
          </div>
        </div>
      )}
    </article>
  )
}

export default function AskPage() {
  const [question, setQuestion] = useState('')
  const [chat, setChat] = useState([])                // oldest first, only in this tab
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const bottom = useRef(null)

  useEffect(() => {
    if (chat.length) bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [chat.length, busy])

  async function ask(text) {
    const q = text.trim()
    if (q.length < 3 || busy) return
    setQuestion(q)
    setBusy(true)
    setError('')
    // the last few turns go along, so follow-up questions like "what about Howrah?" make sense
    const history = chat.slice(-4).map((t) => ({ question: t.question, answer: t.result.answer.slice(0, 4000) }))
    try {
      const result = await api('/api/assistant/ask', { method: 'POST', body: { question: q, history } })
      setChat((c) => [...c, { id: Date.now(), question: q, result }].slice(-10))
      setQuestion('')
    } catch (err) {
      setError(err.message)
    }
    setBusy(false)
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <h1 className="font-display text-4xl flex items-center gap-3">
          <span className="inline-flex w-11 h-11 rounded bg-sindoor text-white items-center justify-center"><Icon name="spark" /></span>
          Ask AI about jobs and careers
        </h1>
        {chat.length > 0 && (
          <button onClick={() => { setChat([]); setError('') }}
                  className="px-3 py-1.5 rounded border border-gray-300 text-sm hover:bg-paper">New chat</button>
        )}
      </div>
      <p className="mt-2 text-gray-600 max-w-2xl">
        Ask anything about jobs: which openings fit you, what to learn, salaries, interviews or your CV.
        You can ask follow-up questions. Answers about openings use only real, live Kolkata jobs on this site.
      </p>

      {chat.length === 0 && (
        <div className="mt-6 flex flex-wrap gap-2">
          {EXAMPLES.map((q) => (
            <button key={q} type="button" onClick={() => ask(q)} disabled={busy}
                    className="px-3 py-1 rounded-full text-sm bg-white border border-gray-300 hover:border-dusk disabled:opacity-50">{q}</button>
          ))}
        </div>
      )}

      <div className="mt-8 space-y-10">
        {chat.map((item) => <Reply key={item.id} item={item} />)}
      </div>

      {busy && <p className="mt-6 text-sm text-gray-500">Reading live jobs and writing an answer. This takes a few seconds.</p>}
      {error && <p className="mt-6 p-4 rounded bg-red-50 text-sindoor text-sm">{error}</p>}

      <form ref={bottom} onSubmit={(e) => { e.preventDefault(); ask(question) }}
            className="sticky bottom-3 mt-8 flex rounded-md overflow-hidden border border-gray-300 bg-white shadow-lg focus-within:ring-2 focus-within:ring-dusk">
        <label htmlFor="question" className="sr-only">Your question</label>
        <input id="question" value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={500}
               placeholder={chat.length ? 'Ask a follow-up, e.g. "What about Howrah?"' : 'e.g. Which banks in Kolkata are hiring freshers?'}
               className="flex-1 min-w-0 px-4 py-3 focus:outline-none" />
        <button disabled={busy || question.trim().length < 3}
                className="px-6 bg-sindoor text-white font-semibold disabled:opacity-50">{busy ? 'Thinking' : 'Ask'}</button>
      </form>
    </div>
  )
}
