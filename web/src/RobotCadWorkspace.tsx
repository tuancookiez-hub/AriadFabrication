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

export function RobotCadWorkspace({ projectId }: { projectId: string }) {
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

  if (error) return <div className="build-error" role="alert">Actual CAD preview unavailable: {error}</div>
  if (!manifest) return <div className="cad-workspace-loading" role="status">Loading prototype CAD parts…</div>

  return (
    <section className="cad-workspace" aria-labelledby="cad-workspace-title">
      <header className="cad-workspace-heading">
        <div><p className="eyebrow">Actual parametric geometry</p><h2 id="cad-workspace-title">Inspect the robot CAD parts</h2><p>Nine separate solids were built from editable CadQuery source. Select a part to orbit it or download its exact geometry.</p></div>
        <span className="cad-status"><i /> Prototype CAD</span>
      </header>
      <div className="cad-workspace-layout">
        <nav className="cad-part-list" aria-label="Robot CAD parts">
          {manifest.parts.map((part) => <button className={part.part_id === selectedId ? 'selected' : ''} key={part.part_id} type="button" onClick={() => setSelectedId(part.part_id)}><span>{label(part.part_id)}</span><small>{part.kernel_valid && part.solid_count === 1 ? 'Valid solid' : 'Needs review'}</small></button>)}
        </nav>
        <div className="cad-part-preview">
          <ModelInspector artifact={artifact} />
          {selected ? <div className="cad-part-actions"><div><strong>{label(selected.part_id)}</strong><span>{Math.round(selected.volume_mm3).toLocaleString()} mm³ · source v{manifest.design_source_version}</span></div><a href={`${artifactRoot}/${selected.step}`} download>Download STEP</a><a href={`${artifactRoot}/${selected.stl}`} download>Download STL</a></div> : null}
        </div>
      </div>
      <div className="cad-next-step"><div><strong>Next: verify before calling it printer-ready</strong><p>Kernel validity is only the first check. Ariad still needs per-part dimensions, clearances, orientation, printability, and real slicer evidence.</p></div><Link className="secondary-action" to={`/chat?project=${encodeURIComponent(projectId)}`}>Ask Codex for a change</Link></div>
    </section>
  )
}
