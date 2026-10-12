// Small line icons (16 px, current colour) for the toolbar: they make buttons look like buttons
// and let the eye find a view or an action before reading its name.

type IconProps = { size?: number };

function Svg({ size = 16, children }: IconProps & { children: React.ReactNode }) {
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor"
      strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

/** The map: steps joined by lines. */
export const MapIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="1.5" y="2" width="4.5" height="3.5" rx="1" />
    <rect x="10" y="6.25" width="4.5" height="3.5" rx="1" />
    <rect x="1.5" y="10.5" width="4.5" height="3.5" rx="1" />
    <path d="M6 3.75h1.5a1.5 1.5 0 0 1 1.5 1.5V6.5a1.5 1.5 0 0 0 1 1.5M6 12.25h1.5A1.5 1.5 0 0 0 9 10.75V9.5a1.5 1.5 0 0 1 1-1.5" />
  </Svg>
);

/** The list: rows. */
export const ListIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5.5 4h9M5.5 8h9M5.5 12h9" />
    <circle cx="2.25" cy="4" r=".6" fill="currentColor" />
    <circle cx="2.25" cy="8" r=".6" fill="currentColor" />
    <circle cx="2.25" cy="12" r=".6" fill="currentColor" />
  </Svg>
);

/** The story: an open book. */
export const StoryIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 4.25C6.6 3.2 4.6 2.75 1.75 2.75v9.5c2.85 0 4.85.45 6.25 1.5 1.4-1.05 3.4-1.5 6.25-1.5v-9.5C11.4 2.75 9.4 3.2 8 4.25Z" />
    <path d="M8 4.25v9.5" />
  </Svg>
);

export const PlusIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 3v10M3 8h10" />
  </Svg>
);

/** Quick note: a pencil. */
export const NoteIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M10.75 2.75 13.25 5.25 5.5 13H3v-2.5l7.75-7.75Z" />
    <path d="M9.25 4.25 11.75 6.75" />
  </Svg>
);

/** Share: an arrow leaving a box. */
export const ShareIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 2v8M5 5l3-3 3 3" />
    <path d="M4 8H3v6h10V8h-1" />
  </Svg>
);

export const GearIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="8" cy="8" r="2.2" />
    <path d="M8 1.5v1.8M8 12.7v1.8M14.5 8h-1.8M3.3 8H1.5M12.6 3.4l-1.3 1.3M4.7 11.3l-1.3 1.3M12.6 12.6l-1.3-1.3M4.7 4.7 3.4 3.4" />
  </Svg>
);

/** The app's mark: a blue rounded square with a stamp ring, as on the app icon. */
export const LogoMark = ({ size = 22 }: IconProps) => (
  <svg className="logo" width={size} height={size} viewBox="0 0 22 22" aria-hidden="true">
    <rect width="22" height="22" rx="5" fill="var(--accent)" />
    <circle cx="11" cy="11" r="5.5" fill="none" stroke="#fff" strokeWidth="2" />
    <circle cx="11" cy="11" r="1.6" fill="#fff" />
  </svg>
);
