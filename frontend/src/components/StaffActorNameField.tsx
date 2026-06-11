import { useId } from 'react'

interface StaffActorNameFieldProps {
  value: string
  onChange: (value: string) => void
  error?: string | null
  className?: string
  showLabel?: boolean
  variant?: 'default' | 'toolbar'
}

export const STAFF_ACTOR_REQUIRED_MESSAGE =
  'Enter your name before saving. This is required for audit because this is a shared staff account.'

export const STAFF_ACTOR_HELPER_TEXT =
  'Required for audit because this is a shared staff account.'

export const StaffActorNameField = ({
  value,
  onChange,
  error,
  className,
  showLabel = true,
  variant = 'default',
}: StaffActorNameFieldProps) => {
  const helperId = useId()
  const labelId = useId()
  const isToolbar = variant === 'toolbar'

  return (
    <label
      className={`staff-actor-field ${isToolbar ? 'staff-actor-field-toolbar' : ''} ${className ?? ''}`.trim()}
    >
      <span
        id={labelId}
        className={showLabel ? 'staff-actor-label' : 'staff-actor-label staff-actor-label-hidden'}
      >
        Your name
      </span>
      <input
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onBlur={() => onChange(value.trim())}
        placeholder="Enter your name"
        autoComplete="name"
        aria-describedby={helperId}
        aria-labelledby={labelId}
      />
      <small
        id={helperId}
        className={`staff-actor-helper-text ${isToolbar ? 'staff-actor-helper-hidden' : ''}`.trim()}
      >
        {STAFF_ACTOR_HELPER_TEXT}
      </small>
      {error ? <small className="upload-validation-text">{error}</small> : null}
    </label>
  )
}
