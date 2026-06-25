import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement> & { size?: number }

const SvgIcon = ({ size = 18, children, ...props }: IconProps) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.75}
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    {...props}
  >
    {children}
  </svg>
)

export const IconHome = (props: IconProps) => (
  <SvgIcon {...props}>
    <path d="M3 11l9-8 9 8" />
    <path d="M5 9.5V21h14V9.5" />
  </SvgIcon>
)

export const IconUpload = (props: IconProps) => (
  <SvgIcon {...props}>
    <path d="M12 16V4" />
    <path d="M7 9l5-5 5 5" />
    <path d="M4 20h16" />
  </SvgIcon>
)

export const IconWarn = (props: IconProps) => (
  <SvgIcon {...props}>
    <path d="M12 3l10 17H2L12 3z" />
    <path d="M12 10v4" />
    <circle cx="12" cy="17" r="0.6" fill="currentColor" />
  </SvgIcon>
)

export const IconSettings = (props: IconProps) => (
  <SvgIcon {...props}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
  </SvgIcon>
)

export const IconSend = (props: IconProps) => (
  <SvgIcon {...props}>
    <path d="M22 2L11 13" />
    <path d="M22 2l-7 20-4-9-9-4 20-7z" />
  </SvgIcon>
)

export const IconHospital = (props: IconProps) => (
  <SvgIcon {...props}>
    <rect x="3" y="6" width="18" height="15" rx="1.5" />
    <path d="M9 6V3h6v3" />
    <path d="M12 11v6" />
    <path d="M9 14h6" />
  </SvgIcon>
)

export const IconBell = (props: IconProps) => (
  <SvgIcon {...props}>
    <path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
    <path d="M10 21a2 2 0 0 0 4 0" />
  </SvgIcon>
)

export const IconChevDown = (props: IconProps) => (
  <SvgIcon {...props}>
    <path d="M6 9l6 6 6-6" />
  </SvgIcon>
)

export const IconChevRight = (props: IconProps) => (
  <SvgIcon {...props}>
    <path d="M9 6l6 6-6 6" />
  </SvgIcon>
)

export const IconFile = (props: IconProps) => (
  <SvgIcon {...props}>
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <path d="M14 2v6h6" />
  </SvgIcon>
)

export const IconCalendar = (props: IconProps) => (
  <SvgIcon {...props}>
    <rect x="3" y="4" width="18" height="18" rx="2" />
    <path d="M16 2v4" />
    <path d="M8 2v4" />
    <path d="M3 10h18" />
  </SvgIcon>
)

export const IconDatabase = (props: IconProps) => (
  <SvgIcon {...props}>
    <ellipse cx="12" cy="5" rx="9" ry="3" />
    <path d="M3 5v6c0 1.7 4 3 9 3s9-1.3 9-3V5" />
    <path d="M3 11v6c0 1.7 4 3 9 3s9-1.3 9-3v-6" />
  </SvgIcon>
)

export const IconGrid = (props: IconProps) => (
  <SvgIcon {...props}>
    <rect x="3" y="3" width="7" height="7" rx="1" />
    <rect x="14" y="3" width="7" height="7" rx="1" />
    <rect x="3" y="14" width="7" height="7" rx="1" />
    <rect x="14" y="14" width="7" height="7" rx="1" />
  </SvgIcon>
)

export const IconRefresh = (props: IconProps) => (
  <SvgIcon {...props}>
    <path d="M21 12a9 9 0 1 1-3-6.7" />
    <path d="M21 4v5h-5" />
  </SvgIcon>
)

export const IconCheck = (props: IconProps) => (
  <SvgIcon {...props}>
    <path d="M20 6L9 17l-5-5" />
  </SvgIcon>
)

export const IconPlus = (props: IconProps) => (
  <SvgIcon {...props}>
    <path d="M12 5v14" />
    <path d="M5 12h14" />
  </SvgIcon>
)

export const IconDownload = (props: IconProps) => (
  <SvgIcon {...props}>
    <path d="M12 4v11" />
    <path d="M7 10l5 5 5-5" />
    <path d="M4 20h16" />
  </SvgIcon>
)

export const IconLogOut = (props: IconProps) => (
  <SvgIcon {...props}>
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
    <path d="M16 17l5-5-5-5" />
    <path d="M21 12H9" />
  </SvgIcon>
)

export const IconMenu = (props: IconProps) => (
  <SvgIcon {...props}>
    <path d="M4 7h16" />
    <path d="M4 12h16" />
    <path d="M4 17h16" />
  </SvgIcon>
)

export const IconX = (props: IconProps) => (
  <SvgIcon {...props}>
    <path d="M18 6L6 18" />
    <path d="M6 6l12 12" />
  </SvgIcon>
)

interface NamedIconProps extends IconProps {
  name: string
}

export const NamedIcon = ({ name, ...props }: NamedIconProps) => {
  switch (name) {
    case 'home':
      return <IconHome {...props} />
    case 'upload':
      return <IconUpload {...props} />
    case 'warn':
      return <IconWarn {...props} />
    case 'settings':
      return <IconSettings {...props} />
    case 'send':
      return <IconSend {...props} />
    case 'hospital':
      return <IconHospital {...props} />
    case 'file':
      return <IconFile {...props} />
    case 'calendar':
      return <IconCalendar {...props} />
    case 'database':
      return <IconDatabase {...props} />
    case 'grid':
      return <IconGrid {...props} />
    case 'logout':
      return <IconLogOut {...props} />
    default:
      return <IconSettings {...props} />
  }
}
