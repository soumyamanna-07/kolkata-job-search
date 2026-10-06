// Short messages at the bottom of the screen ("Saved", "Link copied"). Use: const toast = useToast(); toast('Saved')
import { createContext, useCallback, useContext, useState } from 'react'

const ToastContext = createContext(() => {})

export function ToastProvider({ children }) {
  const [message, setMessage] = useState(null)

  const show = useCallback((text) => {
    const id = Date.now()
    setMessage({ id, text })
    setTimeout(() => setMessage((m) => (m && m.id === id ? null : m)), 2800)
  }, [])

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div role="status" aria-live="polite" className="fixed bottom-5 inset-x-0 flex justify-center pointer-events-none z-50">
        {message && (
          <div key={message.id} className="toast px-4 py-2.5 rounded-md bg-ink text-white text-sm shadow-xl">
            {message.text}
          </div>
        )}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  return useContext(ToastContext)
}
