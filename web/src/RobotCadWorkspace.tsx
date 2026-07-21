import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { ModelInspector, type ModelArtifact } from './ModelInspector'

type Mode = 'cad' | 'verify' | 'slice' | 'package'
type PrototypePart = { part_id: string; step: string; stl: string; glb: string; glb_sha256: string; kernel_valid: boolean; solid_count: number; volume_mm3: number; manufacturing_orientation?: string; assembly_method?: string; bounds_mm?: { x: number; y: number; z: number } }
type ComponentLayout = { glb: string; glb_sha256: string; components: string[]; evidence: string }
type PrototypeManifest = { artifact_kind: 'prototype_geometry'; design_source_version: string; part_count: number; parts: PrototypePart[]; component_layout?: ComponentLayout; claim_boundary: string }
type SlicePart = { part_id: string; slice_status: string; support_risk: string; slicer_warnings: string[]; layers: number; estimated_seconds: number; filament_mass_g: number; gcode_preflight_passed: boolean; geometry: { manifold_mesh: boolean; fits_generic_build_volume: boolean; placed_on_bed: boolean } }
type CalibrationCoupon = { status: string; part_count: number; candidate_clearances_mm: number[]; candidate_hook_engagements_mm: number[]; estimated_seconds: number; filament_mass_g: number; physical_coupon_printed: boolean; path: string; size_bytes: number; checksum_sha256: string }
type PackageManifest = { artifact_kind: 'robot_prototype_fabrication_package'; part_count: number; profile: { printer: string; material: string; slicer: string; calibrated_to_hardware: boolean }; totals: { estimated_seconds: number; filament_mass_g: number }; parts: SlicePart[]; checks: Record<string, boolean>; unresolved_warnings: string[]; first_print_calibration?: CalibrationCoupon; claim_boundary: string; download: { path: string; size_bytes: number; checksum_sha256: string } }

const artifactRoot = '/demo/robot-cad'
const packageRoot = '/demo/robot-package'
const labels: Record<Mode, { eyebrow: string; title: string; copy: string }> = {
  cad: { eyebrow: 'Component-first CAD ready', title: 'Inspect the hardware layout and printable parts.', copy: 'Start with the selected internal envelopes, then choose each separately manufactured part. The shell was built around the Pi and two servos.' },
  verify: { eyebrow: 'Digital checks complete', title: 'Review print preparation.', copy: 'Ariad checked every printed part as a closed mesh, placed it on the bed, and compared it with the generic build volume. Purchased-component fit remains an explicit physical warning.' },
  slice: { eyebrow: 'Real disconnected slice', title: 'Inspect the slicing result.', copy: 'PrusaSlicer produced actual layer and material estimates for every part. Warnings stay attached to the affected part.' },
  package: { eyebrow: 'Prototype package ready', title: 'Download the complete handoff.', copy: 'CAD, meshes, 3MF projects, G-code, profiles, reports, logs, and checksums are bundled together. Nothing was sent to hardware.' },
}

function label(value: string): string { return value.replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase()) }
function duration(seconds: number): string { const hours = Math.floor(seconds / 3600); const minutes = Math.round((seconds % 3600) / 60); return hours ? `${hours}h ${minutes}m` : `${minutes}m` }

export function RobotCadWorkspace({ projectId, mode, onContinue }: { projectId: string; mode: Mode; onContinue: () => void }) {
  const [manifest, setManifest] = useState<PrototypeManifest | null>(null)
  const [packageManifest, setPackageManifest] = useState<PackageManifest | null>(null)
  const [selectedId, setSelectedId] = useState('__components__')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([
      fetch(`${artifactRoot}/manifest.json`, { signal: controller.signal }).then((response) => { if (!response.ok) throw new Error(`CAD manifest request failed (${response.status})`); return response.json() as Promise<PrototypeManifest> }),
      fetch(`${packageRoot}/manifest.json`, { signal: controller.signal }).then((response) => { if (!response.ok) throw new Error(`Package manifest request failed (${response.status})`); return response.json() as Promise<PackageManifest> }),
    ]).then(([cad, packaged]) => {
      if (cad.parts.length !== cad.part_count || packaged.parts.length !== packaged.part_count) throw new Error('Robot artifact manifest is inconsistent')
      setManifest(cad); setPackageManifest(packaged); setSelectedId(cad.component_layout ? '__components__' : cad.parts[0]?.part_id ?? '')
    }).catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Robot artifacts are unavailable') })
    return () => controller.abort()
  }, [])

  const selected = useMemo(() => manifest?.parts.find((part) => part.part_id === selectedId) ?? null, [manifest, selectedId])
  const selectedSlice = useMemo(() => packageManifest?.parts.find((part) => part.part_id === selectedId) ?? null, [packageManifest, selectedId])
  const componentView = selectedId === '__components__' ? manifest?.component_layout ?? null : null
  const artifact: ModelArtifact | null = componentView
    ? { download_url: `${artifactRoot}/${componentView.glb}`, size_bytes: null, checksum_sha256: componentView.glb_sha256 }
    : selected ? { download_url: `${artifactRoot}/${selected.glb}`, size_bytes: null, checksum_sha256: selected.glb_sha256 } : null
  const validParts = manifest?.parts.filter((part) => part.kernel_valid && part.solid_count === 1).length ?? 0
  const copy = labels[mode]

  if (error) return <div className="build-error" role="alert">Robot demo artifacts unavailable: {error}</div>
  if (!manifest || !packageManifest) return <div className="cad-workspace-loading" role="status">Loading robot build artifacts…</div>

  return <section className="cad-workspace" aria-labelledby="cad-workspace-title">
    <header className="cad-workspace-heading"><div><p className="eyebrow">{copy.eyebrow}</p><h2 id="cad-workspace-title">{copy.title}</h2><p>{copy.copy}</p></div><span className="cad-status"><i /> {mode === 'cad' ? `${validParts}/${manifest.part_count} valid solids` : mode === 'verify' ? `${packageManifest.part_count}/${packageManifest.part_count} digitally checked` : mode === 'slice' ? packageManifest.profile.slicer : 'Package assembled'}</span></header>
    <div className="cad-component-basis"><div><strong>Body-driving hardware</strong><span>Pi Zero 2 W · 2× SCS0009 · OV5647 reservation · external 5 V</span></div><small>Battery excluded from Rev A · exact camera, IMU, horn, and cable still require measured units</small></div>
    <div className="cad-workspace-layout">
      <nav className="cad-part-list" aria-label="Robot CAD parts">{manifest.component_layout ? <button className={selectedId === '__components__' ? 'selected component-layout-choice' : 'component-layout-choice'} type="button" onClick={() => setSelectedId('__components__')}><span>Internal hardware layout</span><small>Reference envelopes · not printable</small></button> : null}{manifest.parts.map((part) => <button className={part.part_id === selectedId ? 'selected' : ''} key={part.part_id} type="button" onClick={() => setSelectedId(part.part_id)}><span>{label(part.part_id)}</span><small>{mode === 'slice' || mode === 'package' ? (packageManifest.parts.find((item) => item.part_id === part.part_id)?.slicer_warnings.length ? 'Review warning' : 'Slice passed') : part.kernel_valid && part.solid_count === 1 ? 'Valid solid' : 'Needs review'}</small></button>)}</nav>
      <div className="cad-part-preview"><ModelInspector artifact={artifact} />
        {componentView ? <div className="cad-part-actions component-layout-details"><div><strong>Selected component envelopes</strong><span>{componentView.components.map(label).join(' · ')}</span><small>{componentView.evidence}. These are layout references, not printable geometry.</small></div></div> : null}
        {selected ? <div className="cad-part-actions"><div><strong>{label(selected.part_id)}</strong><span>{Math.round(selected.volume_mm3).toLocaleString()} mm³ · {selected.manufacturing_orientation ?? 'orientation pending'}{selected.bounds_mm ? ` · ${selected.bounds_mm.x} × ${selected.bounds_mm.y} × ${selected.bounds_mm.z} mm` : ''}</span>{selected.assembly_method ? <small>{selected.assembly_method}</small> : null}</div><a href={`${artifactRoot}/${selected.step}`} download>STEP</a><a href={`${artifactRoot}/${selected.stl}`} download>STL</a></div> : null}
        {mode !== 'cad' && selectedSlice ? <div className="robot-check-summary"><span><b>{selectedSlice.geometry.manifold_mesh && selectedSlice.geometry.placed_on_bed ? '✓' : '!'}</b> Manifold and on bed</span><span><b>{selectedSlice.geometry.fits_generic_build_volume ? '✓' : '!'}</b> Fits 220 mm profile</span><span><b>{selectedSlice.gcode_preflight_passed ? '✓' : '!'}</b> G-code preflight</span>{mode === 'slice' || mode === 'package' ? <><span><b>{selectedSlice.layers}</b> layers</span><span><b>{duration(selectedSlice.estimated_seconds)}</b> estimate</span><span><b>{selectedSlice.filament_mass_g} g</b> PETG estimate</span></> : null}</div> : null}
        {(mode === 'slice' || mode === 'package') && selectedSlice?.slicer_warnings.length ? <div className="robot-part-warning"><strong>Slicer review</strong><span>{selectedSlice.slicer_warnings.join(', ')}</span></div> : null}
      </div>
    </div>
    {mode === 'package' ? <><div className="robot-package-summary"><div><strong>{packageManifest.part_count}-part interlocking prototype handoff</strong><span>{duration(packageManifest.totals.estimated_seconds)} combined estimate · {packageManifest.totals.filament_mass_g} g PETG · generic uncalibrated profile</span></div><a className="primary-action" href={`${packageRoot}/${packageManifest.download.path}`} download>Download package ({(packageManifest.download.size_bytes / 1_000_000).toFixed(1)} MB)</a></div>{packageManifest.first_print_calibration ? <div className="calibration-first-print"><div><p className="eyebrow">Before the full robot</p><strong>Print the small fit coupon first</strong><span>Tests five dovetail clearances and three snap engagements · {duration(packageManifest.first_print_calibration.estimated_seconds)} · {packageManifest.first_print_calibration.filament_mass_g} g PETG</span><small>{packageManifest.first_print_calibration.physical_coupon_printed ? 'Physical results recorded' : 'Digitally sliced; physical measurements still required'}</small></div><a className="secondary-action" href={packageManifest.first_print_calibration.path} download>Download calibration coupon ({(packageManifest.first_print_calibration.size_bytes / 1_000).toFixed(0)} KB)</a></div> : null}</> : null}
    <div className="cad-next-step"><div><strong>{mode === 'cad' ? 'Does the layout and model look right?' : mode === 'verify' ? 'Ready for a real disconnected slice' : mode === 'slice' ? 'The digital handoff can now be packaged' : 'Package complete—with honest warnings'}</strong><p>{mode === 'cad' ? 'Inspect the internal hardware layout first, then the nine printable parts. Continue when their relationship is clear.' : mode === 'verify' ? 'All nine printed parts are valid, manifold, on the bed, and inside the generic printer envelope. Exact purchased-unit fit remains unresolved and visible.' : mode === 'slice' ? 'All nine G-code files passed digital preflight. Any slicer warnings remain attached to their parts for review.' : packageManifest.claim_boundary}</p></div><div className="cad-next-actions"><Link className="secondary-action" to={`/chat?project=${encodeURIComponent(projectId)}`}>Ask Codex for a change</Link>{mode !== 'package' ? <button className="primary-action" type="button" onClick={onContinue}>{mode === 'cad' ? 'Check print preparation' : mode === 'verify' ? 'Review real slice' : 'Build package'}</button> : null}</div></div>
  </section>
}
