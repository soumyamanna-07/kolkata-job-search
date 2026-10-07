// Small helpers to show job data nicely.
const RUPEE = '\u20b9'

function money(value) {
  if (value >= 100000) {
    const lakhs = value / 100000
    return `${RUPEE}${lakhs % 1 === 0 ? lakhs : lakhs.toFixed(1)} L`
  }
  if (value >= 1000) return `${RUPEE}${Math.round(value / 1000)}k`
  return `${RUPEE}${value}`
}

export function salaryText(job) {
  const { salary_min: low, salary_max: high } = job
  if (!low && !high) return 'Salary not disclosed'
  const per = { year: '/yr', month: '/month', hour: '/hr' }[job.salary_period] || ''
  if (low && high && low !== high) return `${money(low)} - ${money(high)}${per}`
  return `${money(low || high)}${per}`
}

export function experienceText(job) {
  const { experience_min: low, experience_max: high } = job
  if (low == null && high == null) return null
  if (!low && !high) return 'Fresher'
  if (low != null && high != null && low !== high) return `${low}-${high} yrs`
  return `${low ?? high}+ yrs`
}

export function postedText(dateString) {
  if (!dateString) return null
  const days = Math.floor((Date.now() - new Date(dateString).getTime()) / 86400000)
  if (days <= 0) return 'Today'
  if (days === 1) return 'Yesterday'
  if (days < 30) return `${days} days ago`
  return new Date(dateString).toLocaleDateString('en-IN')
}

export const JOB_TYPE_LABELS = {
  full_time: 'Full-time', part_time: 'Part-time', internship: 'Internship',
  contract: 'Contract', temporary: 'Temporary',
}
export const WORK_MODE_LABELS = { onsite: 'On-site', hybrid: 'Hybrid', remote: 'Remote' }

// job sites whose apply link goes through their own page; their terms ask us to credit them on every job
export const SOURCE_CREDITS = {
  adzuna: { name: 'Adzuna', text: 'Jobs by Adzuna', url: 'https://www.adzuna.in' },
  jooble: { name: 'Jooble', text: 'Jobs by Jooble', url: 'https://in.jooble.org' },
  careerjet: { name: 'Careerjet', text: 'Jobs by Careerjet', url: 'https://www.careerjet.co.in' },
  jobicy: { name: 'Jobicy', text: 'Jobs by Jobicy', url: 'https://jobicy.com' },
}

// company job boards, career pages, recruiters and TPO links open the employer's own page
export function isDirect(job) {
  return !SOURCE_CREDITS[job.source]
}
