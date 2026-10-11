import type { ReactNode, SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function Icon({ children, className, ...props }: IconProps & { children: ReactNode }) {
  return (
    <svg
      className={className ? `icon ${className}` : "icon"}
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      {...props}
    >
      {children}
    </svg>
  );
}

export function IconHome(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4 10.5 12 4l8 6.5" />
      <path d="M6.5 9.8V20h11V9.8" />
    </Icon>
  );
}

export function IconClipboard(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="6" y="4.5" width="12" height="16" rx="2" />
      <path d="M9 4.5h6v3H9z" />
      <path d="M9 11h6M9 14.5h6" />
    </Icon>
  );
}

export function IconMap(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4 7.5 9.5 5l5 2.5L20 5v13.5L14.5 21l-5-2.5L4 21z" />
      <path d="M9.5 5v13.5M14.5 7.5V21" />
    </Icon>
  );
}

export function IconBot(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="5" y="8" width="14" height="11" rx="3" />
      <path d="M12 8V5" />
      <circle cx="12" cy="5" r="1" />
      <circle cx="9.2" cy="13" r="1" fill="currentColor" />
      <circle cx="14.8" cy="13" r="1" fill="currentColor" />
      <path d="M9.5 16.2h5" />
    </Icon>
  );
}

export function IconPlus(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M12 6v12M6 12h12" />
    </Icon>
  );
}

export function IconMic(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="9" y="4" width="6" height="10" rx="3" />
      <path d="M7 12a5 5 0 0 0 10 0M12 17v3" />
    </Icon>
  );
}

export function IconCamera(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4 8.5h3.2l1.3-2h7l1.3 2H20v10H4z" />
      <circle cx="12" cy="13" r="3.2" />
    </Icon>
  );
}

export function IconSave(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M5 5h11l3 3v11H5z" />
      <path d="M8 5v4h7V5M8 19v-5h8v5" />
    </Icon>
  );
}

export function IconClipboardCheck(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="6" y="4.5" width="12" height="16" rx="2" />
      <path d="M9 4.5h6v3H9z" />
      <path d="M9 13.2 11.1 15.2 15.2 10.8" />
    </Icon>
  );
}

export function IconPrinter(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M7 9V4.5h10V9" />
      <path d="M6 9h12v8H6z" />
      <path d="M8 17v3h8v-3" />
      <path d="M16 12.2h.01" />
    </Icon>
  );
}
