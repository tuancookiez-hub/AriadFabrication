import { type FormEvent, useState } from 'react'

import { ModelInspector } from './ModelInspector'
import type { DeclarativeCad } from './types'

type Mode = 'cad' | 'verify' | 'slice' | 'package'

function formatBytes(value: number): string {
  return value < 1024 * 1024
    ? `${(value / 1024).toFixed(1)} KiB`
    : `${(value / (1024 * 1024)).toFixed(1)} MiB`
}

export function LiveDeclarativeWorkspace({
  result,
  mode,
  revising,
  onContinue,
  onRevise,
}: {
  result: DeclarativeCad
  mode: Mode
  revising: boolean
  onContinue: () => void
  onRevise: (instruction: string) => Promise<void>
}) {
  const [instruction, setInstruction] = useState('')
  const preview = result.artifacts.find((item) => item.role === 'browser_preview')
  const artifact = preview
    ? {
        download_url: preview.download_url,
        size_bytes: preview.size_bytes,
        checksum_sha256: preview.checksum_sha256,
      }
    : null
  const heading = mode === 'cad'
    ? 'Codex proposed it. Ariad generated it.'
    : mode === 'verify'
      ? 'Every generated part passed the bounded geometry gate.'
      : mode === 'slice'
        ? 'Select fabrication profiles before slicing.'
        : 'The exact digital geometry is ready to download.'

  async function revise(event: FormEvent) {
    event.preventDefault()
    if (!instruction.trim()) return
    await onRevise(instruction.trim())
    setInstruction('')
  }

  return <section className="cad-workspace live-cad-workspace declarative-cad-workspace" aria-labelledby="declarative-cad-title">
    <header className="cad-workspace-heading">
      <div>
        <p className="eyebrow">Live prompt-to-CSG generation</p>
        <h2 id="declarative-cad-title">{heading}</h2>
        <p>{result.document.summary}</p>
      </div>
      <span className="cad-status"><i /> {result.cache_reused ? 'Exact proposal reused' : 'Generated in this session'}</span>
    </header>

    <div className="live-cad-proof">
      <span><strong>Generation</strong>{result.generation_id}</span>
      <span><strong>Document hash</strong>{result.document_sha256.slice(0, 16)}…</span>
      <span><strong>Geometry</strong>{result.checks.part_count} kernel-valid {result.checks.part_count === 1 ? 'part' : 'parts'}</span>
    </div>

    <div className="cad-workspace-layout">
      <aside className="live-parameter-list declarative-part-list" aria-label="Generated parts">
        <h3>{result.document.title}</h3>
        {result.document.parts.map((part) => {
          const check = result.checks.parts.find((item) => item.part_id === part.part_id)
          return <article key={part.part_id}>
            <strong>{part.name}</strong>
            <span>{part.operations.length} CSG operations</span>
            <small>{part.purpose}</small>
            {check ? <small>{check.bounds_mm.x} × {check.bounds_mm.y} × {check.bounds_mm.z} mm</small> : null}
          </article>
        })}
      </aside>
      <div className="cad-part-preview">
        <ModelInspector artifact={artifact} />
        <div className="live-cad-artifacts">
          {result.artifacts.map((item) => <a href={item.download_url} download key={`${item.role}-${item.filename}`}>
            <strong>{item.part_id ? `${item.part_id} ${item.role.replaceAll('_', ' ')}` : item.role.replaceAll('_', ' ')}</strong>
            <span>{formatBytes(item.size_bytes)} · {item.checksum_sha256.slice(0, 10)}…</span>
          </a>)}
        </div>
      </div>
    </div>

    {mode === 'cad' ? <form className="cad-revision-prompt" onSubmit={revise}>
      <label htmlFor="cad-revision">Change this model</label>
      <div><input id="cad-revision" value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="For example: make the base wider and add two cable holes" /><button className="secondary-action" disabled={revising || !instruction.trim()}>{revising ? 'Codex is revising…' : 'Revise with Codex'}</button></div>
    </form> : null}

    {mode === 'verify' ? <div className="live-check-grid">
      <span><b>✓</b> {result.checks.part_count} parts checked</span>
      <span><b>✓</b> All kernel-valid</span>
      <span><b>✓</b> One solid per part</span>
      <span><b>✓</b> {result.checks.preview_triangle_count.toLocaleString()} preview triangles</span>
    </div> : null}

    {result.document.assumptions.length || result.document.warnings.length ? <details className="advanced-details declarative-assumptions">
      <summary>Assumptions and limits</summary>
      <div>{[...result.document.assumptions, ...result.document.warnings].map((item) => <p key={item}>{item}</p>)}</div>
    </details> : null}

    {mode === 'slice' ? <div className="live-cad-boundary"><strong>No invented G-code</strong><p>The geometry is real, but this new design has not been matched to a printer, material, process, orientation, or support policy. Ariad stops before slicing until those profiles are selected.</p></div> : null}
    {mode === 'package' ? <div className="live-cad-boundary"><strong>Digital geometry handoff</strong><p>{result.claim_boundary}</p></div> : null}

    <div className="cad-next-step">
      <div><strong>{mode === 'package' ? 'Prompt-to-geometry run complete' : 'Continue with visible evidence'}</strong><p>A different prompt or revision produces a different document hash and model.</p></div>
      {mode !== 'package' ? <button className="primary-action" type="button" onClick={onContinue}>{mode === 'cad' ? 'Verify geometry →' : mode === 'verify' ? 'Choose slicing inputs →' : 'Build digital package →'}</button> : null}
    </div>
  </section>
}
