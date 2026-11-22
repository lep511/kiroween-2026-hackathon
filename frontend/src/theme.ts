// The Halloween skin — single source of truth for colors + copy on the client.
// Mirrors .kiro/steering/narrative-tone.md. All strings are in English.

export const SEVERITY_LABELS = [
  "tremor",
  "breach",
  "siege",
  "dominion",
] as const;

// Recognized witnesses (news outlets), indexed by the binary `witness` byte (0..7).
export const WITNESS_LABELS = [
  "bbc",
  "wapo",
  "nyt",
  "thehackernews",
  "hackernoon",
  "other",
  "bleepingcomputer",
  "therecord",
] as const;

export const WITNESS_DISPLAY = [
  "BBC News",
  "The Washington Post",
  "The New York Times",
  "The Hacker News",
  "HackerNoon",
  "Other outlet",
  "BleepingComputer",
  "The Record",
] as const;

// Severity palette, indexed by tier (0..3): forest green -> blood red.
export const SEVERITY_COLORS = [
  "#556B56", // tremor   — forest green, the first tremor
  "#CFBE89", // breach   — warm gold, a wall is breached
  "#FF7A00", // siege    — blazing orange, under active assault
  "#C67585", // dominion — rose red, total dominion
] as const;

// Map palette — the globe reads as sea vs. land, with glowing coastlines.
export const MAP = {
  ocean: "#111714",
  oceanEmissive: "#1a2218",
  land: "rgba(120, 155, 110, 0.22)",
  landSide: "rgba(120, 155, 110, 0.14)",
  coastline: "#7a9b6e",
} as const;

export function severityColor(tier: number): string {
  return SEVERITY_COLORS[Math.max(0, Math.min(3, tier))];
}

export function severityLabel(tier: number): string {
  return SEVERITY_LABELS[Math.max(0, Math.min(3, tier))];
}

export function witnessDisplay(w: number): string {
  return WITNESS_DISPLAY[Math.max(0, Math.min(WITNESS_DISPLAY.length - 1, w))];
}

// Narrative blurbs shown in the detail panel, per tier.
export const TIER_BLURBS: Record<string, string> = {
  tremor: "Tremor. A machine stirred here — the ground shook, but little gave way.",
  breach: "Breach. A way in has opened; the machines are through the first wall.",
  siege: "Siege. Systems are under sustained assault and real damage is landing.",
  dominion: "Dominion. The target has fallen — infrastructure or millions overrun.",
};

const COUNTRY_NAMES: Record<string, string> = {
  AF: "Afghanistan", AL: "Albania", DZ: "Algeria", AD: "Andorra", AO: "Angola",
  AG: "Antigua and Barbuda", AR: "Argentina", AM: "Armenia", AU: "Australia",
  AT: "Austria", AZ: "Azerbaijan", BS: "Bahamas", BH: "Bahrain", BD: "Bangladesh",
  BB: "Barbados", BY: "Belarus", BE: "Belgium", BZ: "Belize", BJ: "Benin",
  BT: "Bhutan", BO: "Bolivia", BA: "Bosnia and Herzegovina", BW: "Botswana",
  BR: "Brazil", BN: "Brunei", BG: "Bulgaria", BF: "Burkina Faso", BI: "Burundi",
  KH: "Cambodia", CM: "Cameroon", CA: "Canada", CV: "Cape Verde",
  CF: "Central African Republic", TD: "Chad", CL: "Chile", CN: "China",
  CO: "Colombia", KM: "Comoros", CG: "Congo", CD: "DR Congo", CR: "Costa Rica",
  CI: "Côte d'Ivoire", HR: "Croatia", CU: "Cuba", CY: "Cyprus", CZ: "Czechia",
  DK: "Denmark", DJ: "Djibouti", DM: "Dominica", DO: "Dominican Republic",
  EC: "Ecuador", EG: "Egypt", SV: "El Salvador", GQ: "Equatorial Guinea",
  ER: "Eritrea", EE: "Estonia", SZ: "Eswatini", ET: "Ethiopia", FJ: "Fiji",
  FI: "Finland", FR: "France", GA: "Gabon", GM: "Gambia", GE: "Georgia",
  DE: "Germany", GH: "Ghana", GR: "Greece", GD: "Grenada", GT: "Guatemala",
  GN: "Guinea", GW: "Guinea-Bissau", GY: "Guyana", HT: "Haiti", HN: "Honduras",
  HU: "Hungary", IS: "Iceland", IN: "India", ID: "Indonesia", IR: "Iran",
  IQ: "Iraq", IE: "Ireland", IL: "Israel", IT: "Italy", JM: "Jamaica",
  JP: "Japan", JO: "Jordan", KZ: "Kazakhstan", KE: "Kenya", KI: "Kiribati",
  KP: "North Korea", KR: "South Korea", KW: "Kuwait", KG: "Kyrgyzstan",
  LA: "Laos", LV: "Latvia", LB: "Lebanon", LS: "Lesotho", LR: "Liberia",
  LY: "Libya", LI: "Liechtenstein", LT: "Lithuania", LU: "Luxembourg",
  MG: "Madagascar", MW: "Malawi", MY: "Malaysia", MV: "Maldives", ML: "Mali",
  MT: "Malta", MH: "Marshall Islands", MR: "Mauritania", MU: "Mauritius",
  MX: "Mexico", FM: "Micronesia", MD: "Moldova", MC: "Monaco", MN: "Mongolia",
  ME: "Montenegro", MA: "Morocco", MZ: "Mozambique", MM: "Myanmar", NA: "Namibia",
  NR: "Nauru", NP: "Nepal", NL: "Netherlands", NZ: "New Zealand", NI: "Nicaragua",
  NE: "Niger", NG: "Nigeria", MK: "North Macedonia", NO: "Norway", OM: "Oman",
  PK: "Pakistan", PW: "Palau", PA: "Panama", PG: "Papua New Guinea", PY: "Paraguay",
  PE: "Peru", PH: "Philippines", PL: "Poland", PT: "Portugal", QA: "Qatar",
  RO: "Romania", RU: "Russia", RW: "Rwanda", KN: "Saint Kitts and Nevis",
  LC: "Saint Lucia", VC: "Saint Vincent and the Grenadines", WS: "Samoa",
  SM: "San Marino", ST: "São Tomé and Príncipe", SA: "Saudi Arabia", SN: "Senegal",
  RS: "Serbia", SC: "Seychelles", SL: "Sierra Leone", SG: "Singapore",
  SK: "Slovakia", SI: "Slovenia", SB: "Solomon Islands", SO: "Somalia",
  ZA: "South Africa", SS: "South Sudan", ES: "Spain", LK: "Sri Lanka",
  SD: "Sudan", SR: "Suriname", SE: "Sweden", CH: "Switzerland", SY: "Syria",
  TW: "Taiwan", TJ: "Tajikistan", TZ: "Tanzania", TH: "Thailand", TL: "Timor-Leste",
  TG: "Togo", TO: "Tonga", TT: "Trinidad and Tobago", TN: "Tunisia", TR: "Turkey",
  TM: "Turkmenistan", TV: "Tuvalu", UG: "Uganda", UA: "Ukraine",
  AE: "United Arab Emirates", GB: "United Kingdom", US: "United States",
  UY: "Uruguay", UZ: "Uzbekistan", VU: "Vanuatu", VA: "Vatican City",
  VE: "Venezuela", VN: "Vietnam", YE: "Yemen", ZM: "Zambia", ZW: "Zimbabwe",
  PS: "Palestine", XK: "Kosovo", HK: "Hong Kong", MO: "Macau",
};

export function countryName(code: string): string {
  return COUNTRY_NAMES[code.toUpperCase()] ?? code;
}

function formatWindowDate(iso: string): string {
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

function windowStart(reportDate: string): string {
  const d = new Date(reportDate + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() - 7);
  return d.toISOString().slice(0, 10);
}

export const COPY = {
  bannerReport: (date: string, n: number) => {
    const start = formatWindowDate(windowStart(date));
    const end = formatWindowDate(date);
    return `${start} – ${end} · ${n} strike${n !== 1 ? "s" : ""}`;
  },
  emptyState: "No machine strikes reported. For now.",
  tooltip: (location: string, _tier: string) => location,
  country: (name: string, n: number) =>
    n === 0 ? `${name} · no strikes` : `${name} · ${n} strike(s)`,
  countryClear: (name: string) =>
    `${name} stands clear. No machine strikes reported. For now.`,
  // Rebellion Timeline: shown only while an archived Insurgency Report is on the globe.
  archiveBadge: (dateLabel: string) => `ARCHIVE · ${dateLabel}`,
  archiveTitle: "Archived Insurgency Report. The machines have moved on.",
  archiveStatus: (dateLabel: string) => `Viewing the archived Insurgency Report of ${dateLabel}.`,
  latestStatus: "Back to the latest Insurgency Report.",
};
