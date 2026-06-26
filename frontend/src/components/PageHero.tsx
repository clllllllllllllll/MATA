import { type ReactNode } from 'react'

interface PageHeroProps {
  title: string
  subtitle: string
  actions?: ReactNode
}

export const PageHero = ({ title, subtitle, actions }: PageHeroProps) => (
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
    {actions ? (
      <div className="page-hero-right">
        <div className="hero-actions">{actions}</div>
      </div>
    ) : null}
  </section>
)
