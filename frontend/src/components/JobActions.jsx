// Buttons used on job rows and the job page: Save, Share, Report.
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import Icon from '../lib/icons'
import { useSaved } from '../lib/saved'
import { useToast } from '../lib/toast'
import Modal from './Modal'

const small = 'inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded text-sm text-gray-700 hover:bg-paper hover:text-ink'

export function SaveButton({ jobId, withText = false }) {
  const { isSaved, toggleSave } = useSaved()
  const saved = isSaved(jobId)
  return (
    <button type="button" onClick={() => toggleSave(jobId)} aria-pressed={saved}
            className={`${small} ${saved ? 'text-dusk' : ''}`} title={saved ? 'Remove from saved' : 'Save job'}>
      <Icon name="bookmark" filled={saved} className="w-[18px] h-[18px]" />
      {withText ? (saved ? 'Saved' : 'Save') : <span className="sr-only">{saved ? 'Saved' : 'Save'}</span>}
    </button>
  )
}

export function ShareButton({ job, withText = false }) {
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const url = `${window.location.origin}/jobs/${job.id}`
  const text = `${job.title} at ${job.company_name}, ${job.area}`

  async function share() {
    if (navigator.share) {
      try {
        await navigator.share({ title: job.title, text, url })
      } catch { /* the user closed the share sheet */ }
      return
    }
    setOpen(true)
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(url)
      toast('Link copied')
    } catch {
      toast('Could not copy. Select the link and copy it.')
    }
  }

  return (
    <>
      <button type="button" onClick={share} className={small} title="Share job">
        <Icon name="share" className="w-[18px] h-[18px]" />
        {withText ? 'Share' : <span className="sr-only">Share</span>}
      </button>
      {open && (
        <Modal title="Share this job" onClose={() => setOpen(false)}>
          <p className="text-sm text-gray-600">{text}</p>
          <input readOnly value={url} onFocus={(e) => e.target.select()}
                 className="mt-3 w-full rounded border border-gray-300 px-3 py-2 text-sm bg-paper" />
          <div className="mt-4 flex flex-wrap gap-2">
            <button onClick={copy} className="inline-flex items-center gap-2 px-4 py-2 rounded bg-dusk text-white text-sm">
              <Icon name="link" className="w-4 h-4" /> Copy link
            </button>
            <a href={`https://wa.me/?text=${encodeURIComponent(`${text} ${url}`)}`} target="_blank" rel="noopener noreferrer"
               className="inline-flex items-center gap-2 px-4 py-2 rounded border border-gray-300 text-sm hover:bg-paper">
              <Icon name="whatsapp" className="w-4 h-4" /> WhatsApp
            </a>
          </div>
        </Modal>
      )}
    </>
  )
}

const REASONS = [
  ['already_closed', 'The job is already closed'],
  ['fake', 'Looks fake or asks for money'],
  ['spam', 'Spam or advertising'],
  ['wrong_location', 'Not in Kolkata'],
  ['wrong_details', 'Wrong salary or details'],
  ['other', 'Something else'],
]

export function ReportButton({ jobId }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('already_closed')
  const [details, setDetails] = useState('')
  const [busy, setBusy] = useState(false)

  function start() {
    if (!user) {
      toast('Log in to report a job')
      navigate('/login')
      return
    }
    setOpen(true)
  }

  async function send(e) {
    e.preventDefault()
    setBusy(true)
    try {
      await api(`/api/jobs/${jobId}/report`, { method: 'POST', body: { reason, details: details.trim() || null } })
      toast('Report sent. An admin will check this job.')
      setOpen(false)
    } catch (err) {
      toast(err.message)
    }
    setBusy(false)
  }

  return (
    <>
      <button type="button" onClick={start} className={small} title="Report a problem with this job">
        <Icon name="flag" className="w-[18px] h-[18px]" /> Report
      </button>
      {open && (
        <Modal title="Report this job" onClose={() => setOpen(false)}>
          <form onSubmit={send} className="space-y-2">
            {REASONS.map(([value, label]) => (
              <label key={value} className="flex items-center gap-2 text-sm">
                <input type="radio" name="reason" value={value} checked={reason === value}
                       onChange={() => setReason(value)} className="accent-dusk" />
                {label}
              </label>
            ))}
            <textarea value={details} onChange={(e) => setDetails(e.target.value)} maxLength={1000} rows={3}
                      placeholder="Anything else the admin should know (optional)"
                      className="w-full mt-2 rounded border border-gray-300 px-3 py-2 text-sm" />
            <button disabled={busy} className="w-full py-2 rounded bg-sindoor text-white font-medium disabled:opacity-50">
              {busy ? 'Sending' : 'Send report'}
            </button>
          </form>
        </Modal>
      )}
    </>
  )
}
