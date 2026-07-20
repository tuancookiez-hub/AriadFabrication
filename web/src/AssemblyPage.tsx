import { useEffect, useState } from 'react'

import conceptUrl from '../../assets/ariad-robot-concept-v1.png'
import { getRobotAssembly } from './api'
import type { AssemblySpec } from './types'

const readable = (value: string) => value.replaceAll('_', ' ')

export function AssemblyPage() {
  const [assembly, setAssembly] = useState<AssemblySpec | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getRobotAssembly(controller.signal).then(setAssembly).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Unknown API error')
    })
    return () => controller.abort()
  }, [])

  if (error) return <div className="assembly-state" role="alert"><strong>Assembly foundation unavailable</strong><p>{error}</p></div>
  if (!assembly) return <div className="assembly-state" role="status">Loading assembly foundation…</div>

  return (
    <div className="assembly-page">
      <section className="assembly-hero">
        <div>
          <p className="eyebrow">Assembly-first design · planning fixture</p>
          <h1 data-route-heading tabIndex={-1}>{assembly.name}</h1>
          <p>{assembly.purpose}</p>
          <div className="assembly-counts" aria-label="Assembly counts">
            <span><strong>{assembly.parts.length}</strong> printable parts</span>
            <span><strong>{assembly.component_envelopes.length}</strong> component envelopes</span>
            <span><strong>{assembly.interfaces.length}</strong> interfaces</span>
            <span><strong>{assembly.unresolved_questions.length}</strong> open decisions</span>
          </div>
        </div>
        <figure className="assembly-concept">
          <img src={conceptUrl} alt="Approved visual concept for a compact two-limb Ariad robot" />
          <figcaption>Approved visual direction—not generated CAD.</figcaption>
        </figure>
      </section>

      <aside className="assembly-boundary">
        <strong>Current evidence boundary</strong>
        <p>{assembly.claim_boundary}</p>
        <div><span>CAD {assembly.cad_generated ? 'available' : 'not generated'}</span><span>Simulation {assembly.simulation_run ? 'run' : 'not run'}</span><span>Hardware disconnected</span></div>
      </aside>

      <section className="assembly-section" aria-labelledby="parts-heading">
        <div className="section-heading"><div><p className="eyebrow">Manufacturing decomposition</p><h2 id="parts-heading">Build it as an assembly, not one mesh</h2></div></div>
        <div className="part-grid">
          {assembly.parts.map((part, index) => (
            <article className="assembly-card" key={part.part_id}>
              <span className="part-number">{String(index + 1).padStart(2, '0')}</span>
              <div><h3>{part.name}</h3><p>{part.role}</p><small>{part.manufacturing_process} · {part.material} · quantity {part.quantity}</small><p className="part-note">{part.notes}</p></div>
            </article>
          ))}
        </div>
      </section>

      <section className="assembly-section" aria-labelledby="components-heading">
        <div className="section-heading"><div><p className="eyebrow">Fit inputs</p><h2 id="components-heading">Component envelopes</h2></div></div>
        <div className="component-grid">
          {assembly.component_envelopes.map((component) => (
            <article className="component-card" key={component.component_id}>
              <div><span className={`evidence-chip evidence-${component.evidence}`}>{component.evidence}</span><h3>{component.name}</h3></div>
              <strong>{component.dimensions_mm.length} × {component.dimensions_mm.width} × {component.dimensions_mm.height} mm</strong>
              <p>{component.source}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="assembly-section" aria-labelledby="interfaces-heading">
        <div className="section-heading"><div><p className="eyebrow">Connection contract</p><h2 id="interfaces-heading">Assembly interfaces</h2></div></div>
        <div className="interface-list">
          {assembly.interfaces.map((item) => (
            <article className="interface-card" key={item.interface_id}>
              <div><span>{readable(item.kind)}</span><h3>{item.name}</h3><p>{item.participants.join(' ↔ ')}</p></div>
              <ul>{item.requirements.map((requirement) => <li key={requirement}>{requirement}</li>)}</ul>
            </article>
          ))}
        </div>
      </section>

      <section className="unresolved-card" aria-labelledby="questions-heading">
        <p className="eyebrow">Required before detailed CAD</p><h2 id="questions-heading">Open engineering decisions</h2>
        <ol>{assembly.unresolved_questions.map((question) => <li key={question}>{question}</li>)}</ol>
      </section>
    </div>
  )
}
