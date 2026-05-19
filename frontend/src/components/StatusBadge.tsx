interface StatusBadgeProps {
  label: string
  tone: 'success' | 'warning' | 'critical' | 'info' | 'neutral'
}

export const StatusBadge = ({ label, tone }: StatusBadgeProps) => (
  <span className={`status-badge badge status-badge-${tone} badge-${tone}`}>{label}</span>
)
