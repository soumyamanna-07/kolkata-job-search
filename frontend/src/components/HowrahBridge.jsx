// Kolkata at dusk, drawn in SVG: the skyline (Victoria Memorial on the left, Salt Lake towers on the right),
// Howrah Bridge over the Hooghly, a country boat and birds. No photo needed, sharp on every screen.
// The bridge truss is generated from the outline of its top chord, so the members always line up.

const DECK = 214                       // road level
const RIVER = 236                      // water line
// top chord of the cantilever truss: anchor arm -> tower -> cantilever arm -> suspended span -> mirror
const TOP = [[40, 196], [150, 150], [330, 34], [470, 128], [540, 150], [600, 140], [660, 150], [730, 128],
  [870, 34], [1050, 150], [1160, 196]]

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

// far skyline: [x, width, height] blocks standing on the river bank
const BLOCKS = [[0, 34, 52], [36, 22, 70], [60, 40, 44], [214, 30, 58], [246, 18, 40],
  [940, 26, 64], [968, 34, 96], [1004, 22, 78], [1028, 38, 118], [1068, 24, 86], [1094, 42, 104],
  [1138, 28, 72], [1168, 32, 90]]
// a few lit windows (deterministic, so the picture is the same on every visit)
const WINDOWS = BLOCKS.flatMap(([x, w, h], i) =>
  [0, 1, 2, 3].filter((k) => (i * 7 + k * 3) % 5 < 2).map((k) => [x + 5 + ((k * 9) % Math.max(w - 10, 1)), RIVER - h + 10 + k * 14]))

function Skyline() {
  return (
    <g fill="#223a52">
      {BLOCKS.map(([x, w, h]) => <rect key={x} x={x} y={RIVER - h} width={w} height={h} />)}
      {/* Victoria Memorial: wide base, drum, dome and the angel on top */}
      <path d="M104 236V204h116v32ZM118 204v-10h88v10ZM138 194v-14h48v14ZM140 180q22-34 44 0ZM161 146h2v-8h-2Z" />
      <path d="M122 204v-8h6v8ZM196 204v-8h6v8Z" />
      <g fill="#f4c430" opacity="0.7">
        {WINDOWS.map(([x, y], i) => <rect key={i} x={x} y={y} width="3" height="4" />)}
      </g>
    </g>
  )
}

function Structure() {
  return (
    <g>
      <path d={TRUSS} stroke="#6b8196" strokeWidth="1.2" fill="none" opacity="0.8" />
      <path d={CHORD} stroke="#8fa3b6" strokeWidth="4" fill="none" strokeLinejoin="round" />
      <path d={TOWERS} stroke="#a9bacb" strokeWidth="3" fill="none" />
      <rect x="20" y={DECK} width="1160" height="7" fill="#3e5063" />
      {/* a yellow taxi and a bus crossing */}
      <rect x="452" y={DECK - 6} width="14" height="6" rx="2" fill="#f4c430" />
      <rect x="760" y={DECK - 9} width="26" height="9" rx="2" fill="#b81d24" />
    </g>
  )
}

export default function HowrahBridge({ className = '' }) {
  return (
    <svg viewBox="0 0 1200 300" preserveAspectRatio="xMidYMax slice" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="hb-sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#17324a" stopOpacity="0" />
          <stop offset="0.45" stopColor="#1f3a52" />
          <stop offset="0.8" stopColor="#3a4d63" />
          <stop offset="1" stopColor="#c27a4c" />
        </linearGradient>
        <linearGradient id="hb-river" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#24394f" />
          <stop offset="1" stopColor="#132536" />
        </linearGradient>
        <radialGradient id="hb-glow" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#f4c430" stopOpacity="0.45" />
          <stop offset="1" stopColor="#f4c430" stopOpacity="0" />
        </radialGradient>
        <clipPath id="hb-above-water"><rect width="1200" height={RIVER} /></clipPath>
      </defs>

      <rect width="1200" height={RIVER} fill="url(#hb-sky)" />
      <circle cx="600" cy="214" r="170" fill="url(#hb-glow)" clipPath="url(#hb-above-water)" />
      <circle className="hb-sun" cx="600" cy="214" r="58" fill="#f4c430" clipPath="url(#hb-above-water)" />
      <Skyline />
      {/* birds heading home */}
      <g stroke="#0f2436" strokeWidth="2" fill="none" strokeLinecap="round" opacity="0.7">
        <path d="M520 92q6-6 12 0q6-6 12 0M556 76q5-5 10 0q5-5 10 0M492 70q4-4 8 0q4-4 8 0" />
      </g>
      <Structure />

      <rect y={RIVER} width="1200" height={300 - RIVER} fill="url(#hb-river)" />
      {/* reflection: the bridge upside down, faint */}
      <g transform={`translate(0 ${2 * RIVER}) scale(1 -1)`} opacity="0.16">
        <Structure />
      </g>
      <g stroke="#f4c430" strokeLinecap="round" opacity="0.55">
        <path d="M560 246h80M575 256h50M588 266h24" strokeWidth="3" />
      </g>
      <g stroke="#9fb0bf" strokeLinecap="round" opacity="0.25">
        <path d="M120 252h60M260 262h40M820 250h70M980 264h50M1080 254h40" strokeWidth="2" />
      </g>
      {/* a country boat (nouka) with its sail */}
      <g fill="#0f2436">
        <path d="M232 262q28 10 64 0l-6 8h-52Z" />
        <path d="M262 260V222l22 32Z" opacity="0.9" />
      </g>
    </svg>
  )
}
