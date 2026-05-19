import { type ReactNode } from 'react'

interface HeroMetaItem {
  label: string
  value: string
}

interface PageHeroProps {
  title: string
  subtitle: string
  meta?: HeroMetaItem[]
  metaInline?: string[]
  actions?: ReactNode
}

export const PageHero = ({ title, subtitle, meta, metaInline, actions }: PageHeroProps) => (
  <section className="hero">
    <div className="hero-left">
      <div className="hero-title-block">
        <span className="hero-accent" />
        <div>
          <h1 className="hero-title">{title}</h1>
          <p className="hero-subtitle">{subtitle}</p>
        </div>
      </div>
    </div>
    <div className="page-hero-right">
      {metaInline && metaInline.length > 0 ? (
        <div className="hero-meta hero-meta-inline">
          {metaInline.map((item, index) => (
            <span key={`${item}-${index}`}>
              {item}
              {index !== metaInline.length - 1 ? <span className="dot" aria-hidden="true" /> : null}
            </span>
          ))}
        </div>
      ) : null}
      {!metaInline && meta && meta.length > 0 ? (
        <div className="hero-meta">
          {meta.map((item, index) => (
            <span key={item.label}>
              {item.label}: {item.value}
              {index !== meta.length - 1 ? <span className="dot" aria-hidden="true" /> : null}
            </span>
          ))}
        </div>
      ) : null}
      {actions ? <div className="hero-actions">{actions}</div> : null}
    </div>
  </section>
)
