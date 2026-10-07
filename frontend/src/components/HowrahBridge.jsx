// Kolkata over the Hooghly, drawn in SVG: the skyline (Victoria Memorial on the left, Salt Lake towers on the right),
// Howrah Bridge, a country boat and birds. No photo needed, sharp on every screen.
// The scene follows the visitor's clock: by day the sun rises behind the bridge, at night a full moon rises
// and the bridge lamps come on. The bridge truss is generated from the outline of its top chord.
import { useEffect, useState } from 'react'

const DECK = 214                       // road level
const RIVER = 236                      // water line
// top chord of the cantilever truss: anchor arm -> tower -> cantilever arm -> suspended span -> mirror
const TOP = [[40, 196], [150, 150], [330, 34], [470, 128], [540, 150], [600, 140], [660, 150], [730, 128],
  [870, 34], [1050, 150], [1160, 196]]

// day from 6 in the morning to 6 in the evening, by the visitor's own clock
export function skyPhase(date = new Date()) {
  const hour = date.getHours()
  return hour >= 6 && hour < 18 ? 'day' : 'night'
}

// the current phase, checked again every minute so an open page changes at sunrise and sunset
export function useSkyPhase() {
  const [phase, setPhase] = useState(() => skyPhase())
  useEffect(() => {
    const timer = setInterval(() => setPhase(skyPhase()), 60000)
    return () => clearInterval(timer)
  }, [])
  return phase
}

function topY(x) {
  for (let i = 1; i < TOP.length; i++) {
    const [x0, y0] = TOP[i - 1]
    const [x1, y1] = TOP[i]
    if (x <= x1) return y0 + ((y1 - y0) * (x - x0)) / (x1 - x0)
  }
  return TOP[TOP.length - 1][1]
}

function truss() {
  const lines = []
  const step = 28
  for (let x = 40; x <= 1160; x += step) {
    const y = topY(x)
    lines.push(`M${x} ${y}V${DECK}`)                                  // vertical member
    const nx = Math.min(x + step, 1160)
    if (nx > x) lines.push(`M${x} ${y}L${nx} ${DECK}M${x} ${DECK}L${nx} ${topY(nx)}`)  // X bracing
  }
  return lines.join('')
}

const TRUSS = truss()
const CHORD = 'M' + TOP.map(([x, y]) => `${x} ${y}`).join('L')
// each tower: two legs that lean in, tied by cross-bracing
const TOWERS = [330, 870].map((x) => `M${x - 12} ${RIVER}L${x - 4} 30M${x + 12} ${RIVER}L${x + 4} 30`
  + [60, 100, 140, 180].map((y) => `M${x - 9} ${y}L${x + 9} ${y + 32}M${x + 9} ${y}L${x - 9} ${y + 32}`).join('')).join('')
// lamps along the road, lit at night
const LAMPS = Array.from({ length: 29 }, (_, i) => 40 + i * 40)

// far skyline: [x, width, height] blocks standing on the river bank
const BLOCKS = [[0, 34, 52], [36, 22, 70], [60, 40, 44], [214, 30, 58], [246, 18, 40],
  [940, 26, 64], [968, 34, 96], [1004, 22, 78], [1028, 38, 118], [1068, 24, 86], [1094, 42, 104],
  [1138, 28, 72], [1168, 32, 90]]
// lit windows (deterministic, so the picture is the same on every visit); more of them at night
const windows = (share) => BLOCKS.flatMap(([x, w, h], i) =>
  [0, 1, 2, 3, 4].filter((k) => k * 14 + 16 < h && (i * 7 + k * 3) % 5 < share)
    .map((k) => [x + 5 + ((k * 9) % Math.max(w - 10, 1)), RIVER - h + 10 + k * 14]))

// a few stars in the SVG sky (the hero behind it has the rest)
const STARS = [[70, 40], [180, 22], [262, 70], [410, 30], [520, 18], [690, 34], [780, 16], [960, 26], [1060, 50],
  [1130, 20], [1180, 64], [24, 96], [452, 60], [740, 70]]

const LOOK = {
  day: {
    horizon: '#f2a65a', horizonOpacity: 0.95, glow: '#ffb347', glowOpacity: 0.55,
    skyline: '#3a2b4c', windows: windows(1), windowColor: '#ffd36b', windowOpacity: 0.55,
    truss: '#3f3a5c', chord: '#2c2944', towers: '#35314f', deck: '#221e35',
    riverTop: '#8c5468', riverBottom: '#2a2343', shine: '#ffc964', ripple: '#f6c99a', boat: '#1d1830',
  },
  night: {
    horizon: '#1e3a5c', horizonOpacity: 0.9, glow: '#cfe0ff', glowOpacity: 0.32,
    skyline: '#0f1d2d', windows: windows(3), windowColor: '#f4c430', windowOpacity: 0.85,
    truss: '#4c6480', chord: '#7590ad', towers: '#8aa1b8', deck: '#23364a',
    riverTop: '#11243a', riverBottom: '#050c17', shine: '#e8eefc', ripple: '#9fb0bf', boat: '#08121f',
  },
}

function Skyline({ look }) {
  return (
    <g fill={look.skyline}>
      {BLOCKS.map(([x, w, h]) => <rect key={x} x={x} y={RIVER - h} width={w} height={h} />)}
      {/* Victoria Memorial: wide base, drum, dome and the angel on top */}
      <path d="M104 236V204h116v32ZM118 204v-10h88v10ZM138 194v-14h48v14ZM140 180q22-34 44 0ZM161 146h2v-8h-2Z" />
      <path d="M122 204v-8h6v8ZM196 204v-8h6v8Z" />
      <g fill={look.windowColor} opacity={look.windowOpacity}>
        {look.windows.map(([x, y], i) => <rect key={i} x={x} y={y} width="3" height="4" />)}
      </g>
    </g>
  )
}

function Structure({ look }) {
  return (
    <g>
      <path d={TRUSS} stroke={look.truss} strokeWidth="1.2" fill="none" opacity="0.9" />
      <path d={CHORD} stroke={look.chord} strokeWidth="4" fill="none" strokeLinejoin="round" />
      <path d={TOWERS} stroke={look.towers} strokeWidth="3" fill="none" />
      <rect x="20" y={DECK} width="1160" height="7" fill={look.deck} />
      {/* a yellow taxi and a bus crossing */}
      <rect x="452" y={DECK - 6} width="14" height="6" rx="2" fill="#f4c430" />
      <rect x="760" y={DECK - 9} width="26" height="9" rx="2" fill="#b81d24" />
    </g>
  )
}

function Sun() {
  return (
    <g clipPath="url(#hb-above-water)">
      <circle cx="600" cy="214" r="190" fill="url(#hb-glow)" />
      <circle className="hb-sun" cx="600" cy="214" r="60" fill="url(#hb-sun-disc)" />
    </g>
  )
}

function Moon() {
  return (
    <g clipPath="url(#hb-above-water)">
      <circle cx="600" cy="128" r="104" fill="url(#hb-glow)" />
      <g className="hb-moon">
        <circle cx="600" cy="128" r="44" fill="url(#hb-moon-disc)" />
        {/* soft grey seas on the moon */}
        <g fill="#c9cfd8" opacity="0.55">
          <circle cx="586" cy="116" r="9" />
          <circle cx="612" cy="138" r="12" />
          <circle cx="618" cy="110" r="5" />
          <circle cx="590" cy="146" r="5" />
        </g>
      </g>
    </g>
  )
}

function Lamps() {
  return (
    <g>
      <g fill="#ffd36b" opacity="0.55" filter="url(#hb-soft)">
        {LAMPS.map((x) => <circle key={x} cx={x} cy={DECK - 3} r="5" />)}
      </g>
      <g fill="#fff1b8">
        {LAMPS.map((x) => <circle key={x} cx={x} cy={DECK - 3} r="1.6" />)}
      </g>
      {/* red warning lights on top of the two towers */}
      <g fill="#ff5a5f">
        <circle cx="330" cy="30" r="2.6" /><circle cx="870" cy="30" r="2.6" />
      </g>
      <g fill="#ff5a5f" opacity="0.5" filter="url(#hb-soft)">
        <circle cx="330" cy="30" r="7" /><circle cx="870" cy="30" r="7" />
      </g>
    </g>
  )
}

export default function HowrahBridge({ className = '', phase }) {
  const clockPhase = useSkyPhase()
  const night = (phase || clockPhase) === 'night'
  const look = night ? LOOK.night : LOOK.day

  return (
    <svg viewBox="0 0 1200 300" preserveAspectRatio="xMidYMax slice" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="hb-sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={look.horizon} stopOpacity="0" />
          <stop offset="0.55" stopColor={look.horizon} stopOpacity="0.25" />
          <stop offset="1" stopColor={look.horizon} stopOpacity={look.horizonOpacity} />
        </linearGradient>
        <linearGradient id="hb-river" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={look.riverTop} />
          <stop offset="1" stopColor={look.riverBottom} />
        </linearGradient>
        <radialGradient id="hb-glow" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor={look.glow} stopOpacity={look.glowOpacity} />
          <stop offset="1" stopColor={look.glow} stopOpacity="0" />
        </radialGradient>
        <radialGradient id="hb-sun-disc" cx="0.5" cy="0.45" r="0.55">
          <stop offset="0" stopColor="#fff4c2" />
          <stop offset="0.55" stopColor="#ffd25e" />
          <stop offset="1" stopColor="#f59a2c" />
        </radialGradient>
        <radialGradient id="hb-moon-disc" cx="0.42" cy="0.4" r="0.65">
          <stop offset="0" stopColor="#fffdf4" />
          <stop offset="0.7" stopColor="#eef0ea" />
          <stop offset="1" stopColor="#d5dbe4" />
        </radialGradient>
        <filter id="hb-soft" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="3" />
        </filter>
        <clipPath id="hb-above-water"><rect width="1200" height={RIVER} /></clipPath>
      </defs>

      <rect width="1200" height={RIVER} fill="url(#hb-sky)" />
      {night && (
        <g fill="#ffffff">
          {STARS.map(([x, y], i) => <circle key={i} cx={x} cy={y} r={i % 3 === 0 ? 1.4 : 0.9} opacity={0.5 + (i % 3) * 0.15} />)}
        </g>
      )}
      {night ? <Moon /> : <Sun />}
      <Skyline look={look} />
      {!night && (
        /* birds heading out for the day */
        <g stroke="#2a2140" strokeWidth="2" fill="none" strokeLinecap="round" opacity="0.75">
          <path d="M520 92q6-6 12 0q6-6 12 0M556 76q5-5 10 0q5-5 10 0M492 70q4-4 8 0q4-4 8 0" />
        </g>
      )}
      <Structure look={look} />
      {night && <Lamps />}

      <rect y={RIVER} width="1200" height={300 - RIVER} fill="url(#hb-river)" />
      {/* reflection: the bridge upside down, faint */}
      <g transform={`translate(0 ${2 * RIVER}) scale(1 -1)`} opacity={night ? 0.22 : 0.18}>
        <Structure look={look} />
      </g>
      {/* the sun or moon shining on the water */}
      <g stroke={look.shine} strokeLinecap="round" opacity={night ? 0.7 : 0.75}>
        <path d="M556 244h88M570 253h60M582 262h36M592 271h16" strokeWidth="3" />
      </g>
      {night && (
        /* lamp light falling on the river */
        <g stroke="#ffd36b" strokeLinecap="round" opacity="0.35">
          {LAMPS.filter((_, i) => i % 2 === 0).map((x) => <path key={x} d={`M${x} 242v${8 + (x % 3) * 4}`} strokeWidth="2" />)}
        </g>
      )}
      <g stroke={look.ripple} strokeLinecap="round" opacity="0.25">
        <path d="M120 252h60M260 262h40M820 250h70M980 264h50M1080 254h40" strokeWidth="2" />
      </g>
      {/* a country boat (nouka) with its sail; a lantern on board at night */}
      <g fill={look.boat}>
        <path d="M232 262q28 10 64 0l-6 8h-52Z" />
        <path d="M262 260V222l22 32Z" opacity="0.9" />
      </g>
      {night && (
        <g>
          <circle cx="288" cy="258" r="6" fill="#ffd36b" opacity="0.5" filter="url(#hb-soft)" />
          <circle cx="288" cy="258" r="1.8" fill="#fff1b8" />
        </g>
      )}
    </svg>
  )
}
