import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { ModelInspector, type ModelArtifact } from './ModelInspector'

type PrototypePart = {
  part_id: string
  step: string
  stl: string
  glb: string
  glb_sha256: string
  kernel_valid: boolean
  solid_count: number
  volume_mm3: number
  manufacturing_orientation?: string
  bounds_mm?: { x: number; y: number; z: number }
}

type PrototypeManifest = {
  artifact_kind: 'prototype_geometry'
  design_source_version: string
  part_count: number
  parts: PrototypePart[]
  claim_boundary: string
}

const artifactRoot = '/demo/robot-cad'

function label(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase())
}

export function RobotCadWorkspace({ projectId, mode, onContinue }: { projectId: string; mode: 'cad' | 'verify'; onContinue: () => void }) {
  const [manifest, setManifest] = useState<PrototypeManifest | null>(null)
  const [selectedId, setSelectedId] = useState('front_shell')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    fetch(`${artifactRoot}/manifest.json`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Prototype manifest request failed (${response.status})`)
        return response.json() as Promise<PrototypeManifest>
      })
      .then((value) => {
        if (value.artifact_kind !== 'prototype_geometry' || value.parts.length !== value.part_count) throw new Error('Prototype manifest is inconsistent')
        setManifest(value)
        setSelectedId(value.parts[0]?.part_id ?? '')
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Prototype CAD is unavailable')
      })
    return () => controller.abort()
  }, [])

  const selected = useMemo(() => manifest?.parts.find((part) => part.part_id === selectedId) ?? null, [manifest, selectedId])
  const artifact: ModelArtifact | null = selected ? {
    download_url: `${artifactRoot}/${selected.glb}`,
    size_bytes: null,
    checksum_sha256: selected.glb_sha256,
  } : null
  const validParts = manifest?.parts.filter((part) => part.kernel_valid && part.solid_count === 1).length ?? 0

  if (error) return <div className="build-error" role="alert">Actual CAD preview unavailable: {error}</div>
  if (!manifest) return <div className="cad-workspace-loading" role="status">Loading prototype CAD parts…</div>

  return (
    <section className="cad-workspace" aria-labelledby="cad-workspace-title">
      <header className="cad-workspace-heading">
        <div><p className="eyebrow">{mode === 'cad' ? 'CAD ready to inspect' : 'Geometry checked · print readiness next'}</p><h2 id="cad-workspace-title">{mode === 'cad' ? 'Inspect the model before print checks.' : 'The model passed basic geometry checks.'}</h2><p>{mode === 'cad' ? 'Rotate the preview and choose each separately manufactured part. Ask Codex for a change or continue when the shape looks right.' : 'Ariad confirmed one closed solid per part. Clearance, support risk, and real component fit still need evidence before slicing.'}</p></div>
        <span className="cad-status"><i /> {validParts}/{manifest.part_count} valid solids</span>
      </header>
      <div className="cad-workspace-layout">
        <nav className="cad-part-list" aria-label="Robot CAD parts">
          {manifest.parts.map((part) => <button className={part.part_id === selectedId ? 'selected' : ''} key={part.part_id} type="button" onClick={() => setSelectedId(part.part_id)}><span>{label(part.part_id)}</span><small>{part.kernel_valid && part.solid_count === 1 ? 'Valid solid' : 'Needs review'}</small></button>)}
        </nav>
        <div className="cad-part-preview">
          <ModelInspector artifact={artifact} />
          {selected ? <div className="cad-part-actions"><div><strong>{label(selected.part_id)}</strong><span>{Math.round(selected.volume_mm3).toLocaleString()} mm³ · {selected.manufacturing_orientation ?? 'manufacturing orientation pending'}{selected.bounds_mm ? ` · ${selected.bounds_mm.x} × ${selected.bounds_mm.y} × ${selected.bounds_mm.z} mm` : ''}</span></div><a href={`${artifactRoot}/${selected.step}`} download>Download STEP</a><a href={`${artifactRoot}/${selected.stl}`} download>Download STL</a></div> : null}
        </div>
      </div>
      <div className="cad-next-step"><div><strong>{mode === 'cad' ? 'Does the model look right?' : 'One blocker before slicing'}</strong><p>{mode === 'cad' ? 'Continue to let Ariad check geometry and print preparation. Your model and choices stay here if you go back.' : 'Robot-specific clearance and support-risk checks are not connected yet. Ariad stops here instead of pretending the model is printer-ready.'}</p></div><div className="cad-next-actions"><Link className="secondary-action" to={`/chat?project=${encodeURIComponent(projectId)}`}>Ask Codex for a change</Link>{mode === 'cad' ? <button className="primary-action" type="button" onClick={onContinue}>Check print readiness</button> : null}</div></div>
    </section>
  )
}
