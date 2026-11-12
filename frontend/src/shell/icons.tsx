import type { SVGProps } from "react";

/** Line icons on a 24 px grid, drawn in the current text colour; decorative (the control carries the name). */
function Icon({ children, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={22}
      height={22}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      {children}
    </svg>
  );
}

type IconProps = SVGProps<SVGSVGElement>;

export const OverviewIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect x="3.5" y="3.5" width="7" height="9" rx="1.5" />
    <rect x="13.5" y="3.5" width="7" height="5" rx="1.5" />
    <rect x="13.5" y="11.5" width="7" height="9" rx="1.5" />
    <rect x="3.5" y="15.5" width="7" height="5" rx="1.5" />
  </Icon>
);

/** The hub of the brand mark: a centre with four connected nodes. */
export const ProvidersIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="2.5" />
    <circle cx="12" cy="4.5" r="1.75" />
    <circle cx="19.5" cy="12" r="1.75" />
    <circle cx="12" cy="19.5" r="1.75" />
    <circle cx="4.5" cy="12" r="1.75" />
    <path d="M12 6.25v3.25M17.75 12H14.5M12 14.5v3.25M9.5 12H6.25" />
  </Icon>
);

export const ProtocolIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M8.5 6.5h11M8.5 12h11M8.5 17.5h11" />
    <circle cx="4.5" cy="6.5" r="0.75" />
    <circle cx="4.5" cy="12" r="0.75" />
    <circle cx="4.5" cy="17.5" r="0.75" />
  </Icon>
);

export const SettingsIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M4 7h9M17 7h3M4 17h3M11 17h9" />
    <circle cx="15" cy="7" r="2" />
    <circle cx="9" cy="17" r="2" />
  </Icon>
);

export const SignOutIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M14 4.5h3.5a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H14" />
    <path d="M10.5 8 6.5 12l4 4M6.5 12H16" />
  </Icon>
);

export const SunIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="3.75" />
    <path d="M12 3v1.75M12 19.25V21M3 12h1.75M19.25 12H21M5.6 5.6l1.25 1.25M17.15 17.15l1.25 1.25M5.6 18.4l1.25-1.25M17.15 6.85l1.25-1.25" />
  </Icon>
);

export const MoonIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M19.5 14.25A7.75 7.75 0 0 1 9.75 4.5a7.75 7.75 0 1 0 9.75 9.75Z" />
  </Icon>
);

export const SystemIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect x="3.5" y="4.5" width="17" height="11.5" rx="2" />
    <path d="M9 20h6M12 16v4" />
  </Icon>
);
