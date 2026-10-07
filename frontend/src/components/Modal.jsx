// A simple dialog box. Closes with Escape, the X button, or a click outside.
import { useEffect } from 'react'
import Icon from '../lib/icons'

export default function Modal({ title, onClose, children }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-40 flex items-end sm:items-center justify-center bg-ink/50 p-0 sm:p-4"
         onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label={title}
           className="w-full sm:max-w-md bg-white rounded-t-lg sm:rounded-lg shadow-2xl overflow-hidden">
        <div className="laal-paar" />
        <div className="flex items-center justify-between px-5 pt-4">
          <h2 className="font-display text-xl">{title}</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-paper" aria-label="Close">
            <Icon name="close" />
          </button>
        </div>
        <div className="px-5 pb-5 pt-2">{children}</div>
      </div>
    </div>
  )
}
