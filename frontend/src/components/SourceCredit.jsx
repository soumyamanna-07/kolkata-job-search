// "Jobs by <site>" credit for jobs that come from job sites. Shows the site's logo when we have one
// (Adzuna's terms require their logo, at least 116 x 23 px), otherwise the text credit.
export default function SourceCredit({ credit, className = '' }) {
  if (!credit) return null
  return (
    <a href={credit.url} target="_blank" rel="noopener noreferrer" title={credit.text}
       className={`inline-flex items-center gap-1.5 hover:underline ${className}`}>
      {credit.logo ? (
        <>
          <span>Jobs by</span>
          <img src={credit.logo} alt={credit.name} width="116" height="23" loading="lazy"
               className="h-[23px] w-auto min-w-[116px] object-contain object-left" />
        </>
      ) : credit.text}
    </a>
  )
}
