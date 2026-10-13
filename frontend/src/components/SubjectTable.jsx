// Editable table of syllabus subjects. Used by the admin check page and the curriculum report page.
// subjects: [{ semester, code, name, kind, is_elective, options, credits, topics, skills? }]
const KINDS = [['theory', 'Theory'], ['lab', 'Lab'], ['project', 'Project'], ['other', 'Other']]
const cell = 'w-full rounded border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-dusk'

export function emptySubject(semester = null) {
  return { semester, code: '', name: '', kind: 'theory', is_elective: false, options: [], credits: null, topics: '' }
}

// what the API accepts (drops the skills column and empty values)
export function cleanSubjects(subjects) {
  return subjects
    .filter((s) => s.name && s.name.trim().length >= 2)
    .map((s) => ({
      semester: s.semester ? Number(s.semester) : null,
      code: (s.code || '').trim() || null,
      name: s.name.trim(),
      kind: s.kind || 'theory',
      is_elective: !!s.is_elective,
      options: s.is_elective ? (s.options || []).map((o) => o.trim()).filter(Boolean) : [],
      credits: s.credits === '' || s.credits === null || s.credits === undefined ? null : Number(s.credits),
      topics: s.topics || null,
    }))
}

export default function SubjectTable({ subjects, onChange, showSkills = false, caption }) {
  const update = (i, changes) => onChange(subjects.map((s, j) => (j === i ? { ...s, ...changes } : s)))
  const remove = (i) => onChange(subjects.filter((_, j) => j !== i))
  const add = () => onChange([...subjects, emptySubject(subjects.at(-1)?.semester ?? null)])

  return (
    <div>
      <div className="overflow-x-auto border border-gray-200 rounded bg-white">
        <table className="w-full text-sm">
          {caption && <caption className="text-left p-2 text-gray-600">{caption}</caption>}
          <thead className="bg-paper text-left text-gray-700">
            <tr>
              <th scope="col" className="p-2 w-16">Sem</th>
              <th scope="col" className="p-2 w-28">Code</th>
              <th scope="col" className="p-2 min-w-56">Subject</th>
              <th scope="col" className="p-2 w-28">Type</th>
              <th scope="col" className="p-2 min-w-48">Elective choices</th>
              {showSkills && <th scope="col" className="p-2 min-w-40">Skills found</th>}
              <th scope="col" className="p-2 w-10"><span className="sr-only">Remove</span></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {subjects.map((s, i) => (
              <tr key={i} className="align-top">
                <td className="p-1.5">
                  <input type="number" min="1" max="10" aria-label={`Semester of subject ${i + 1}`} value={s.semester ?? ''}
                         onChange={(e) => update(i, { semester: e.target.value === '' ? null : Number(e.target.value) })}
                         className={cell} />
                </td>
                <td className="p-1.5">
                  <input maxLength={40} aria-label={`Code of subject ${i + 1}`} value={s.code ?? ''}
                         onChange={(e) => update(i, { code: e.target.value })} className={cell} />
                </td>
                <td className="p-1.5">
                  <input maxLength={300} aria-label={`Name of subject ${i + 1}`} value={s.name}
                         onChange={(e) => update(i, { name: e.target.value })} className={cell} />
                </td>
                <td className="p-1.5">
                  <select aria-label={`Type of subject ${i + 1}`} value={s.kind}
                          onChange={(e) => update(i, { kind: e.target.value })} className={cell}>
                    {KINDS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                  </select>
                </td>
                <td className="p-1.5">
                  <label className="flex items-center gap-1.5 text-xs text-gray-700">
                    <input type="checkbox" checked={!!s.is_elective}
                           onChange={(e) => update(i, { is_elective: e.target.checked })} />
                    Elective
                  </label>
                  {s.is_elective && (
                    <input aria-label={`Choices of subject ${i + 1}, separated by /`} placeholder="Choice A / Choice B"
                           value={(s.options || []).join(' / ')}
                           onChange={(e) => update(i, { options: e.target.value.split('/').map((o) => o.trimStart()) })}
                           className={`${cell} mt-1`} />
                  )}
                </td>
                {showSkills && (
                  <td className="p-1.5 text-xs text-gray-700">
                    {(s.skills || []).length ? s.skills.join(', ') : <span className="text-gray-400">none</span>}
                  </td>
                )}
                <td className="p-1.5">
                  <button type="button" onClick={() => remove(i)} aria-label={`Remove ${s.name || `subject ${i + 1}`}`}
                          className="px-2 py-1 rounded text-gray-500 hover:text-sindoor hover:bg-red-50">
                    {'\u2715'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button type="button" onClick={add} className="mt-2 px-3 py-1.5 rounded border border-gray-300 text-sm hover:border-dusk">
        Add a subject
      </button>
    </div>
  )
}
