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
  const validParts = manifest?.parts.filter((part) => part.kernel_valid && part.solid_count === 1).length ?? 0

  if (error) return <div className="build-error" role="alert">Actual CAD preview unavailable: {error}</div>
  if (!manifest) return <div className="cad-workspace-loading" role="status">Loading prototype CAD parts…</div>

  return (
    <section className="cad-workspace" aria-labelledby="cad-workspace-title">
      <header className="cad-workspace-heading">
        <div><p className="eyebrow">Stage 3 complete · Stage 4 active</p><h2 id="cad-workspace-title">CAD generated. Verification is next.</h2><p>Stay in this workspace: inspect each manufacturing-oriented part while Ariad carries the same build into geometry and printability checks.</p></div>
        <span className="cad-status"><i /> {validParts}/{manifest.part_count} valid solids</span>
      </header>
      <div className="cad-flow-strip" aria-label="CAD continuation status"><span className="done"><b>3</b><strong>CAD</strong><small>Parts available</small></span><span className="active"><b>4</b><strong>Verify</strong><small>9 solids checked</small></span><span><b>5</b><strong>Slice</strong><small>Automatic after pass</small></span><span><b>6</b><strong>Package</strong><small>Automatic after slice</small></span></div>
      <div className="cad-workspace-layout">
        <nav className="cad-part-list" aria-label="Robot CAD parts">
          {manifest.parts.map((part) => <button className={part.part_id === selectedId ? 'selected' : ''} key={part.part_id} type="button" onClick={() => setSelectedId(part.part_id)}><span>{label(part.part_id)}</span><small>{part.kernel_valid && part.solid_count === 1 ? 'Valid solid' : 'Needs review'}</small></button>)}
        </nav>
        <div className="cad-part-preview">
          <ModelInspector artifact={artifact} />
          {selected ? <div className="cad-part-actions"><div><strong>{label(selected.part_id)}</strong><span>{Math.round(selected.volume_mm3).toLocaleString()} mm³ · {selected.manufacturing_orientation ?? 'manufacturing orientation pending'}{selected.bounds_mm ? ` · ${selected.bounds_mm.x} × ${selected.bounds_mm.y} × ${selected.bounds_mm.z} mm` : ''}</span></div><a href={`${artifactRoot}/${selected.step}`} download>Download STEP</a><a href={`${artifactRoot}/${selected.stl}`} download>Download STL</a></div> : null}
        </div>
      </div>
      <div className="cad-next-step"><div><strong>No page change is required</strong><p>When every verification gate passes, Ariad advances to Slice automatically and then builds the Package. If a gate is blocked, Codex asks one focused question here. This prototype currently has {validParts}/{manifest.part_count} valid solids; robot-specific clearance and support-risk checks are not connected yet.</p></div><Link className="secondary-action" to={`/chat?project=${encodeURIComponent(projectId)}`}>Adjust this design with Codex</Link></div>
    </section>
  )
}
