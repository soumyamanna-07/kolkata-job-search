// "Log in, then come back here": /login?next=/jobs/123
export function loginUrl(path) {
  return `/login?next=${encodeURIComponent(path)}`
}

// only our own pages, never another website (//evil.com or https://...)
export function safeNext(value) {
  return value && value.startsWith('/') && !value.startsWith('//') ? value : '/'
}
