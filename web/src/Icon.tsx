const paths: Record<string, React.ReactNode> = {
  water: <><path d="M3 8c3-4 6 4 9 0s6 4 9 0M3 16c3-4 6 4 9 0s6 4 9 0" /></>,
  tram: <><rect x="5" y="5" width="14" height="14" rx="3" /><path d="M5 12h14M9 5V2h6M8 19l-2 3M16 19l2 3M9 16h.01M15 16h.01" /></>,
  target: <><circle cx="12" cy="12" r="7" /><circle cx="12" cy="12" r="2" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  minus: <path d="M5 12h14" />,
  play: <path d="m8 5 11 7-11 7z" />,
  pause: <><path d="M8 5v14M16 5v14" /></>,
  reset: <><path d="M4 10a8 8 0 1 1 1 8M4 4v6h6" /></>,
  arrow: <><path d="M5 17 19 3M8 3h11v11" /></>,
  'trend-up': <><path d="M4 17 10 11l4 4 6-7" /><path d="M14 8h6v6" /></>,
  'trend-down': <><path d="M4 7l6 6 4-4 6 7" /><path d="M14 16h6v-6" /></>,
  'trend-flat': <><path d="M4 12h16" /><path d="m16 8 4 4-4 4" /></>,
  chevron: <path d="m6 9 6 6 6-6" />,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7h.01" /></>,
  download: <><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5" /></>,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  check: <path d="m5 12 5 5L20 7" />,
  alert: <><path d="M12 3 2.5 20h19L12 3Z" /><path d="M12 10v4M12 17h.01" /></>,
  question: <><circle cx="12" cy="12" r="9" /><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.7M12 17h.01" /></>,
  route: <><circle cx="6" cy="18" r="2.5" /><circle cx="18" cy="6" r="2.5" /><path d="M8 17h5a4 4 0 0 0 0-8H11a4 4 0 0 1 0-8" transform="rotate(180 12 12)" /></>,
  expand: <><path d="M4 9V4h5M20 15v5h-5M20 9V4h-5M4 15v5h5" /></>,
  collapse: <><path d="M9 4v5H4M15 20v-5h5M15 4v5h5M9 20v-5H4" /></>,
};
export default function Icon({ name, size = 18, strokeWidth = 1.6 }: { name: string; size?: number; strokeWidth?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] ?? paths.info}</svg>;
}
