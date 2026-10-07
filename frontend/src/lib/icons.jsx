// Small line icons used across the app (24x24, drawn with the current text colour).
const PATHS = {
  search: 'M11 4a7 7 0 1 0 0 14a7 7 0 0 0 0-14ZM20 20l-4-4',
  bookmark: 'M6 3h12v18l-6-4l-6 4Z',
  share: 'M18 8a3 3 0 1 0 0-6a3 3 0 0 0 0 6ZM6 15a3 3 0 1 0 0-6a3 3 0 0 0 0 6ZM18 22a3 3 0 1 0 0-6a3 3 0 0 0 0 6ZM8.6 13.5l6.8 4M15.4 6.5l-6.8 4',
  flag: 'M5 21V4h11l-2 4l2 4H5',
  bell: 'M6 16V11a6 6 0 0 1 12 0v5l2 2H4ZM10 21h4',
  file: 'M6 2h8l5 5v15H6ZM14 2v5h5M9 13h7M9 17h7',
  spark: 'M12 3l2 6l6 2l-6 2l-2 6l-2-6l-6-2l6-2Z',
  chart: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  link: 'M10 14a4 4 0 0 0 6 0l3-3a4 4 0 0 0-6-6l-1 1M14 10a4 4 0 0 0-6 0l-3 3a4 4 0 0 0 6 6l1-1',
  menu: 'M4 6h16M4 12h16M4 18h16',
  close: 'M6 6l12 12M18 6L6 18',
  check: 'M5 12l5 5L20 7',
  external: 'M14 4h6v6M20 4l-9 9M18 14v6H4V6h6',
  pin: 'M12 22s7-6.5 7-12a7 7 0 0 0-14 0c0 5.5 7 12 7 12ZM12 12.5a2.5 2.5 0 1 0 0-5a2.5 2.5 0 0 0 0 5Z',
  rupee: 'M7 4h11M7 9h11M7 4c6 0 8 1.5 8 5s-3 5-8 5l8 7',
  briefcase: 'M3 8h18v12H3ZM8 8V5h8v3M3 13h18',
  clock: 'M12 21a9 9 0 1 0 0-18a9 9 0 0 0 0 18ZM12 7v5l3 2',
  user: 'M12 12a4 4 0 1 0 0-8a4 4 0 0 0 0 8ZM4 21a8 8 0 0 1 16 0',
  logout: 'M15 4h4v16h-4M10 8l-4 4l4 4M6 12h10',
  upload: 'M12 16V4M7 9l5-5l5 5M4 20h16',
  sun: 'M12 16a4 4 0 1 0 0-8a4 4 0 0 0 0 8ZM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4',
  moon: 'M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z',
  whatsapp: 'M4 20l1.5-4.5A8 8 0 1 1 9 19ZM9 9c0 3 3 6 6 6l1-2l-2-1l-1 1c-1-.5-2-1.5-2.5-2.5l1-1l-1-2Z',
}

export default function Icon({ name, className = 'w-5 h-5', filled = false, title }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill={filled ? 'currentColor' : 'none'} stroke="currentColor"
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" role={title ? 'img' : undefined}
         aria-hidden={title ? undefined : true}>
      {title && <title>{title}</title>}
      <path d={PATHS[name]} />
    </svg>
  )
}
