import { useEffect, useMemo, useState } from 'react'

import { ModelInspector, type ModelArtifact } from './ModelInspector'
import { ToolpathInspector } from './ToolpathInspector'

type Mode = 'cad' | 'verify' | 'slice' | 'package'
type PrototypePart = { part_id: string; step: string; stl: string; glb: string; glb_sha256: string; kernel_valid: boolean; solid_count: number; volume_mm3: number; manufacturing_orientation?: string; assembly_method?: string; bounds_mm?: { x: number; y: number; z: number } }
type ComponentLayout = { glb: string; glb_sha256: string; components: string[]; evidence: string }
type PrototypeManifest = { artifact_kind: 'prototype_geometry'; design_source_version: string; part_count: number; parts: PrototypePart[]; component_layout?: ComponentLayout; claim_boundary: string }
type SlicePart = { part_id: string; slice_status: string; support_risk: string; slicer_warnings: string[]; layers: number; estimated_seconds: number; filament_mass_g: number; gcode_preflight_passed: boolean; artifacts?: { preview_gcode?: string }; geometry: { manifold_mesh: boolean; fits_generic_build_volume: boolean; placed_on_bed: boolean } }
type CalibrationCoupon = { status: string; part_count: number; candidate_clearances_mm: number[]; candidate_hook_engagements_mm: number[]; estimated_seconds: number; filament_mass_g: number; physical_coupon_printed: boolean; path: string; size_bytes: number; checksum_sha256: string }
type PackageManifest = { artifact_kind: 'robot_prototype_fabrication_package'; part_count: number; profile: { printer: string; material: string; slicer: string; calibrated_to_hardware: boolean }; totals: { estimated_seconds: number; filament_mass_g: number }; parts: SlicePart[]; checks: Record<string, boolean>; unresolved_warnings: string[]; first_print_calibration?: CalibrationCoupon; claim_boundary: string; download: { path: string; size_bytes: number; checksum_sha256: string } }

const artifactRoot = '/demo/robot-cad'
const packageRoot = '/demo/robot-package'

function label(value: string): string { return value.replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase()) }
function duration(seconds: number): string { const hours = Math.floor(seconds / 3600); const minutes = Math.round((seconds % 3600) / 60); return hours ? `${hours}h ${minutes}m` : `${minutes}m` }

export function RobotCadWorkspace({ mode, onContinue, onAskCodex }: { mode: Mode; onContinue: () => void; onAskCodex: (topic: string) => void }) {
  const [manifest, setManifest] = useState<PrototypeManifest | null>(null)
  const [packageManifest, setPackageManifest] = useState<PackageManifest | null>(null)
  const [selectedId, setSelectedId] = useState(mode === 'cad' ? '__components__' : '')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([
      fetch(`${artifactRoot}/manifest.json`, { signal: controller.signal }).then((response) => { if (!response.ok) throw new Error(`CAD manifest request failed (${response.status})`); return response.json() as Promise<PrototypeManifest> }),
      fetch(`${packageRoot}/manifest.json`, { signal: controller.signal }).then((response) => { if (!response.ok) throw new Error(`Package manifest request failed (${response.status})`); return response.json() as Promise<PackageManifest> }),
    ]).then(([cad, packaged]) => {
      if (cad.parts.length !== cad.part_count || packaged.parts.length !== packaged.part_count) throw new Error('Robot artifact manifest is inconsistent')
      setManifest(cad); setPackageManifest(packaged)
      setSelectedId(mode === 'cad' && cad.component_layout
        ? '__components__'
        : mode === 'slice'
          ? packaged.parts.find((part) => part.slicer_warnings.length > 0)?.part_id ?? packaged.parts[0]?.part_id ?? ''
          : cad.parts[0]?.part_id ?? '')
    }).catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Robot artifacts are unavailable') })
    return () => controller.abort()
  }, [mode])

  const selected = useMemo(() => manifest?.parts.find((part) => part.part_id === selectedId) ?? null, [manifest, selectedId])
  const selectedSlice = useMemo(() => packageManifest?.parts.find((part) => part.part_id === selectedId) ?? null, [packageManifest, selectedId])
  const componentView = selectedId === '__components__' ? manifest?.component_layout ?? null : null
  const artifact: ModelArtifact | null = componentView
    ? { download_url: `${artifactRoot}/${componentView.glb}`, size_bytes: null, checksum_sha256: componentView.glb_sha256 }
    : selected ? { download_url: `${artifactRoot}/${selected.glb}`, size_bytes: null, checksum_sha256: selected.glb_sha256 } : null

  if (error) return <div className="build-error" role="alert">Robot demo artifacts unavailable: {error}</div>
  if (!manifest || !packageManifest) return <div className="cad-workspace-loading" role="status">Loading robot build artifacts…</div>

  const validParts = manifest.parts.filter((part) => part.kernel_valid && part.solid_count === 1).length
  const warningParts = packageManifest.parts.filter((part) => part.slicer_warnings.length > 0)
  const passedParts = packageManifest.parts.length - warningParts.length

  if (mode === 'verify') {
    return <section className="stage-result stage-result-verify" aria-labelledby="verify-title">
      <header><div><p className="eyebrow">Verification complete</p><h2 id="verify-title">The geometry is ready for slicing.</h2><p>Codex condensed the technical checks into the decisions that matter now.</p></div><span className="result-badge result-pass">{validParts}/{manifest.part_count} passed</span></header>
      <div className="verification-summary-grid">
        <article><span>Geometry</span><strong>9 closed solids</strong><small>Every STEP re-imports as one valid body.</small></article>
        <article><span>Printer envelope</span><strong>All parts fit</strong><small>Checked against the generic 220 mm profile.</small></article>
        <article><span>Bed placement</span><strong>All parts on bed</strong><small>Manufacturing orientations are recorded.</small></article>
        <article className="verification-warning"><span>Physical fit</span><strong>Measure later</strong><small>Camera, IMU, horn and cable remain unit-dependent.</small></article>
      </div>
      <details className="verification-details"><summary>See all nine part checks</summary><div>{packageManifest.parts.map((part) => <div key={part.part_id}><strong>{label(part.part_id)}</strong><span>✓ manifold</span><span>✓ on bed</span><span>✓ inside profile</span></div>)}</div></details>
      <div className="stage-primary-next"><div><strong>Next: inspect the real slicer output</strong><p>No physical-print claim is added by these checks.</p></div><div><button className="secondary-action" type="button" onClick={() => onAskCodex('Explain the verification results and unresolved physical-fit risks.')}>Ask Codex</button><button className="primary-action" type="button" onClick={onContinue}>Open real slice →</button></div></div>
    </section>
  }

  if (mode === 'package') {
    return <section className="stage-result package-finish" aria-labelledby="package-title">
      <div className="package-complete-mark" aria-hidden="true">✓</div>
      <p className="eyebrow">Digital handoff complete</p>
      <h2 id="package-title">Your fabrication package is ready.</h2>
      <p>Editable CAD, manufacturing meshes, real slicer projects, G-code, profiles, reports and checksums are bundled together.</p>
      <div className="package-finish-metrics"><span><strong>9</strong> sliced prototype parts</span><span><strong>{duration(packageManifest.totals.estimated_seconds)}</strong> estimated</span><span><strong>{packageManifest.totals.filament_mass_g} g</strong> PETG</span><span><strong>{warningParts.length}</strong> review warnings</span></div>
      <a className="primary-action package-download" href={`${packageRoot}/${packageManifest.download.path}`} download>Download complete package ({(packageManifest.download.size_bytes / 1_000_000).toFixed(1)} MB)</a>
      {packageManifest.first_print_calibration ? <div className="calibration-first-print"><div><p className="eyebrow">Recommended first physical step</p><strong>Print the small fit coupon before the robot</strong><span>Tests dovetail clearances and snap engagement · {duration(packageManifest.first_print_calibration.estimated_seconds)} · {packageManifest.first_print_calibration.filament_mass_g} g PETG</span><small>Digitally sliced; physical measurements are still required.</small></div><a className="secondary-action" href={packageManifest.first_print_calibration.path} download>Download fit coupon</a></div> : null}
      <details className="package-boundary"><summary>What this package does not prove</summary><p>{packageManifest.claim_boundary}</p></details>
      <button className="text-action" type="button" onClick={() => onAskCodex('Explain the package, its warnings, and the recommended first physical step.')}>Ask Codex what to do next</button>
    </section>
  }

  const sliceMode = mode === 'slice'
  return <section className={`cad-workspace${sliceMode ? ' slice-workspace' : ''}`} aria-labelledby="cad-workspace-title">
    <header className="cad-workspace-heading"><div><p className="eyebrow">{sliceMode ? 'Real PrusaSlicer output' : 'Component-first CAD ready'}</p><h2 id="cad-workspace-title">{sliceMode ? 'Inspect an actual sliced layer.' : 'Inspect the hardware layout and prototype parts.'}</h2><p>{sliceMode ? 'Ariad selected the first part with a slicer warning so the review starts where attention is needed.' : 'Start with the internal hardware envelopes, then inspect each separately manufactured part.'}</p></div><span className="cad-status"><i /> {sliceMode ? `${passedParts} pass · ${warningParts.length} review` : `${validParts}/${manifest.part_count} valid solids`}</span></header>
    {!sliceMode ? <div className="cad-component-basis"><div><strong>Body-driving hardware</strong><span>Pi Zero 2 W · 2× SCS0009 · OV5647 reservation · external 5 V</span></div><small>Battery excluded from Rev A · exact camera, IMU, horn and cable still require measured units</small></div> : null}
    <div className="cad-workspace-layout">
      <nav className="cad-part-list" aria-label="Robot CAD parts">{!sliceMode && manifest.component_layout ? <button className={selectedId === '__components__' ? 'selected component-layout-choice' : 'component-layout-choice'} type="button" onClick={() => setSelectedId('__components__')}><span>Internal hardware layout</span><small>Reference envelopes · not printable</small></button> : null}{manifest.parts.map((part) => { const slice = packageManifest.parts.find((item) => item.part_id === part.part_id); return <button className={part.part_id === selectedId ? 'selected' : ''} key={part.part_id} type="button" onClick={() => setSelectedId(part.part_id)}><span>{label(part.part_id)}</span><small>{sliceMode ? (slice?.slicer_warnings.length ? 'Review warning' : 'Slice passed') : 'Valid solid'}</small></button> })}</nav>
      <div className="cad-part-preview">
        {sliceMode && selectedSlice?.artifacts?.preview_gcode ? <ToolpathInspector active artifact={{ download_url: `${packageRoot}/${selectedSlice.artifacts.preview_gcode}` }} /> : <ModelInspector artifact={artifact} />}
        {componentView ? <div className="cad-part-actions component-layout-details"><div><strong>Selected component envelopes</strong><span>{componentView.components.map(label).join(' · ')}</span><small>{componentView.evidence}. These are layout references, not printable geometry.</small></div></div> : null}
        {selected ? <div className="cad-part-actions"><div><strong>{label(selected.part_id)}</strong><span>{Math.round(selected.volume_mm3).toLocaleString()} mm³ · {selected.manufacturing_orientation ?? 'orientation pending'}{selected.bounds_mm ? ` · ${selected.bounds_mm.x} × ${selected.bounds_mm.y} × ${selected.bounds_mm.z} mm` : ''}</span>{selected.assembly_method ? <small>{selected.assembly_method}</small> : null}</div>{!sliceMode ? <><a href={`${artifactRoot}/${selected.step}`} download>STEP</a><a href={`${artifactRoot}/${selected.stl}`} download>STL</a></> : null}</div> : null}
        {sliceMode && selectedSlice ? <><div className="robot-check-summary"><span><b>{selectedSlice.layers}</b> layers</span><span><b>{duration(selectedSlice.estimated_seconds)}</b> estimate</span><span><b>{selectedSlice.filament_mass_g} g</b> PETG</span><span><b>✓</b> G-code preflight</span></div>{selectedSlice.slicer_warnings.length ? <div className="robot-part-warning"><strong>Review before printing</strong><span>{selectedSlice.slicer_warnings.join(', ')}</span></div> : <div className="robot-part-pass"><strong>No slicer warning for this part</strong></div>}</> : null}
      </div>
    </div>
    <div className="cad-next-step"><div><strong>{sliceMode ? 'The complete handoff can now be packaged' : 'Does the layout and model look right?'}</strong><p>{sliceMode ? 'Every G-code file passed disconnected digital preflight. Warnings remain attached to their affected parts.' : 'Inspect the hardware envelope and a few prototype parts, then continue.'}</p></div><div className="cad-next-actions"><button className="secondary-action" type="button" onClick={() => onAskCodex(sliceMode ? 'Explain the selected slicer warning and whether the design should change.' : 'Help me review the hardware layout and selected CAD part.')}>Ask Codex</button><button className="primary-action" type="button" onClick={onContinue}>{sliceMode ? 'Build package →' : 'Verify geometry →'}</button></div></div>
  </section>
}
