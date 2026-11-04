const PATHS = {
  mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3",
  stop: "M7 7h10v10H7z",
  send: "M5 12h14M13 6l6 6-6 6",
  speaker: "M4 9v6h4l5 4V5L8 9H4zM16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12",
  muted: "M4 9v6h4l5 4V5L8 9H4zM17 9l5 6M22 9l-5 6",
  flag: "M5 21V4M5 4h11l-2 4 2 4H5",
  bell: "M6 17h12l-1.5-2V11a4.5 4.5 0 0 0-9 0v4zM10.5 20a1.8 1.8 0 0 0 3 0",
  back: "M15 6l-6 6 6 6",
  chart: "M4 19h16M7 16v-5M12 16V8M17 16v-8",
  trash: "M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13",
  check: "M5 12l5 5 9-10",
  clock: "M12 7v5l3 2M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z",
  spark: "M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6",
  minus: "M5 12h14",
  plus: "M12 5v14M5 12h14",
  whistle: "M4 12a5 5 0 1 0 10 0V9h7V6H9a5 5 0 0 0-5 6z",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={PATHS[name]} />
    </svg>
  );
}
