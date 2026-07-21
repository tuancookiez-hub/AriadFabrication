import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { BuildSessionPage } from './BuildSessionPage'

afterEach(() => {
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

const intake = {
  schema_version: '1.19.0', contract_version: '1.0.0', prompt_sha256: 'a'.repeat(64),
  provider: { configured: false, reason: 'No model configured.' },
  route: { lane: 'functional_parametric', status: 'needs_input', summary: 'A two-servo robot enclosure', reason: 'Exact components must be confirmed.', questions: ['Which servo should define the joint?'] },
  executed: false, claim_boundary: 'Intake only.', hardware_actions: false,
}

function response(value: object) {
  return new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

function missing() {
  return new Response(JSON.stringify({ detail: 'No proposal available.' }), { status: 404, headers: { 'Content-Type': 'application/json' } })
}

function robotPackage() {
  return {
    artifact_kind: 'robot_prototype_fabrication_package', part_count: 1,
    profile: { printer: 'generic_open_fdm_220_v1', material: 'generic_petg_175_v1', slicer: 'PrusaSlicer 2.9.6', calibrated_to_hardware: false },
    totals: { estimated_seconds: 3600, filament_mass_g: 10 },
    parts: [{ part_id: 'front_shell', slice_status: 'passed_with_warnings', support_risk: 'review_slicer_warnings', slicer_warnings: ['Bridge review'], layers: 100, estimated_seconds: 3600, filament_mass_g: 10, gcode_preflight_passed: true, geometry: { manifold_mesh: true, fits_generic_build_volume: true, placed_on_bed: true } }],
    checks: { all_kernel_valid: true, all_single_solids: true, all_fit_generic_build_volume: true, all_gcode_preflight_passed: true, component_fit_verified: false, assembly_clearance_verified: false, physical_print_verified: false },
    first_print_calibration: { status: 'digitally_sliced_awaiting_physical_calibration', part_count: 6, candidate_clearances_mm: [0.2, 0.3, 0.4, 0.5, 0.6], candidate_hook_engagements_mm: [0.4, 0.8, 1.2], estimated_seconds: 4200, filament_mass_g: 13.3, physical_coupon_printed: false, path: '/demo/interlock-coupon/coupon.zip', size_bytes: 600_000, checksum_sha256: 'd'.repeat(64) },
    unresolved_warnings: ['Physical print unverified.'], claim_boundary: 'Digital package only.',
    download: { path: 'robot.zip', size_bytes: 1_000_000, checksum_sha256: 'c'.repeat(64) },
  }
}

describe('BuildSessionPage', () => {
  it('presents the demo example as an assembly plan instead of generated concept art', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/api/v1/session')) return response({ schema_version: '1.19.0', session_token: 'browser-secret' })
      return response(intake)
    }))
    render(<MemoryRouter><BuildSessionPage /></MemoryRouter>)

    expect(screen.getByText('Codex will guide this build.')).toBeInTheDocument()
    expect(screen.getByText('Ask only what matters')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Use robot example' }))
    expect(screen.getByLabelText('What should Ariad help you make?')).toHaveValue('Make a cute two-servo robot around a Raspberry Pi Zero 2 W, two SCS0009 servos, a camera, and an IMU. Give it exactly two long rotating side limbs and no fixed feet so it can explore recovery after a fall. Use separate serviceable printed parts and external regulated power for the first revision.')
  })

  it('turns one prompt into editable defaults and keeps assumptions visible', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/api/v1/session')) return response({ schema_version: '1.19.0', session_token: 'browser-secret' })
      return response(intake)
    }))
    render(<MemoryRouter><BuildSessionPage /></MemoryRouter>)

    fireEvent.change(screen.getByLabelText('What should Ariad help you make?'), { target: { value: 'Make a cute two-servo robot.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))

    expect(await screen.findByRole('heading', { name: 'Review the choices that shape the result' })).toBeInTheDocument()
    expect(screen.getByDisplayValue('multi-part robot enclosure')).toBeInTheDocument()
    expect(screen.getByDisplayValue('PETG')).toBeInTheDocument()
    expect(screen.getByText('Use a Pi Zero 2 W and SCS0009 servos now; select the exact camera, IMU, and power cable before physical release.')).toBeInTheDocument()
    expect(screen.queryByText(/configure GPT/i)).not.toBeInTheDocument()
    expect(screen.getByText(/Approve it once/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '← Back to idea' }))
    expect(screen.getByLabelText('What should Ariad help you make?')).toHaveValue('Make a cute two-servo robot.')
  })

  it('records one explicit approval without forcing a second confirmation screen', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/v1/session')) return response({ schema_version: '1.19.0', session_token: 'browser-secret' })
      if (url.endsWith('/api/v1/intake')) return response(intake)
      if (url.endsWith('/api/v1/projects') && init?.method === 'POST') return response({ project_id: 'project_demo', title: 'Robot', prompt: 'Make a robot.' })
      if (url.endsWith('/draft')) return response({ status: 'ready_for_confirmation', missing_fields: [] })
      if (url.endsWith('/design-proposal')) return missing()
      if (url.endsWith('/design-plan')) return response({ lane: 'functional_parametric', geometry_strategy: 'Separate parts.', critical_features: [], assembly_interfaces: [], constraints: [], unresolved_questions: ['Choose servo.'] })
      if (url.endsWith('/demo/robot-cad/manifest.json')) return response({ artifact_kind: 'prototype_geometry', design_source_version: '0.2.0', part_count: 1, claim_boundary: 'Prototype only.', parts: [{ part_id: 'front_shell', step: 'front_shell.step', stl: 'front_shell.stl', glb: 'front_shell.glb', glb_sha256: 'b'.repeat(64), kernel_valid: true, solid_count: 1, volume_mm3: 1000 }] })
      if (url.endsWith('/demo/robot-package/manifest.json')) return response(robotPackage())
      return response({ project_id: 'project_demo', job_id: 'job_demo', revision_id: 'rev_demo', evidence_level: 'R0' })
    }))
    render(<MemoryRouter><BuildSessionPage /></MemoryRouter>)

    fireEvent.change(screen.getByLabelText('What should Ariad help you make?'), { target: { value: 'Make a robot.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Approve and continue' }))

    expect(await screen.findByRole('heading', { name: 'These parts define the robot body.' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Use this hardware layout' }))
    expect(await screen.findByRole('heading', { name: 'Does this arrangement match what you meant?' })).toBeInTheDocument()
    expect(screen.getByText('Pi and servo architecture precedes the shell · visual intent, not physical fit evidence.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Approve blueprint and inspect CAD' }))
    expect(await screen.findByRole('heading', { name: 'Inspect the hardware layout and prototype parts.' })).toBeInTheDocument()
    expect(screen.queryByText(/R0 evidence/i)).not.toBeInTheDocument()
  })

  it('continues the robot Design plan into inspectable prototype CAD', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/v1/session')) return response({ schema_version: '1.19.0', session_token: 'browser-secret' })
      if (url.endsWith('/api/v1/intake')) return response(intake)
      if (url.endsWith('/api/v1/projects') && init?.method === 'POST') return response({ project_id: 'project_demo', title: 'Robot', prompt: 'Make a robot.' })
      if (url.endsWith('/draft')) return response({ status: 'ready_for_confirmation', missing_fields: [] })
      if (url.endsWith('/brief-confirmation')) return response({ project_id: 'project_demo', job_id: 'job_demo', revision_id: 'rev_demo', evidence_level: 'R0' })
      if (url.endsWith('/design-proposal')) return missing()
      if (url.endsWith('/design-plan')) return response({ lane: 'functional_parametric', geometry_strategy: 'Separate parts.', critical_features: [], assembly_interfaces: [], constraints: [], unresolved_questions: ['Choose servo.'] })
      if (url.endsWith('/demo/robot-cad/manifest.json')) return response({ artifact_kind: 'prototype_geometry', design_source_version: '0.2.0', part_count: 1, claim_boundary: 'Prototype only.', parts: [{ part_id: 'front_shell', step: 'front_shell.step', stl: 'front_shell.stl', glb: 'front_shell.glb', glb_sha256: 'b'.repeat(64), kernel_valid: true, solid_count: 1, volume_mm3: 1000, manufacturing_orientation: 'source prototype orientation', bounds_mm: { x: 94, y: 48, z: 78 } }] })
      if (url.endsWith('/demo/robot-package/manifest.json')) return response(robotPackage())
      if (url.endsWith('/demo/robot-cad/front_shell.glb')) return new Response(new ArrayBuffer(0), { status: 200 })
      throw new Error(`Unexpected request: ${url}`)
    }))
    const view = render(<MemoryRouter><BuildSessionPage /></MemoryRouter>)

    fireEvent.change(screen.getByLabelText('What should Ariad help you make?'), { target: { value: 'Make a robot.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Approve and continue' }))

    expect(await screen.findByRole('heading', { name: 'These parts define the robot body.' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Use this hardware layout' }))
    expect(await screen.findByRole('heading', { name: 'Does this arrangement match what you meant?' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Approve blueprint and inspect CAD' }))
    expect(await screen.findByRole('heading', { name: 'Inspect the hardware layout and prototype parts.' })).toBeInTheDocument()
    expect(screen.getByText('What Codex prepared')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Front Shell.*Valid solid/i })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Verify geometry →' }))
    expect(await screen.findByRole('heading', { name: 'The geometry is ready for slicing.' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Open real slice →' }))
    expect(await screen.findByRole('heading', { name: 'Inspect an actual sliced layer.' })).toBeInTheDocument()
    expect(screen.getByText('Bridge review')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Build package →' }))
    expect(await screen.findByRole('heading', { name: 'Your fabrication package is ready.' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Download complete package/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Download fit coupon/i })).toBeInTheDocument()
    expect(screen.getByText(/physical measurements are still required/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Back to slice/i }))
    fireEvent.click(screen.getByRole('button', { name: /Back to verification/i }))
    fireEvent.click(screen.getByRole('button', { name: '← Back to CAD' }))
    expect(await screen.findByRole('heading', { name: 'Inspect the hardware layout and prototype parts.' })).toBeInTheDocument()

    view.unmount()
    render(<MemoryRouter><BuildSessionPage /></MemoryRouter>)
    expect(await screen.findByRole('heading', { name: 'Inspect the hardware layout and prototype parts.' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '← Back to blueprint' }))
    expect(screen.getByRole('heading', { name: 'Does this arrangement match what you meant?' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '← Back to components' }))
    expect(screen.getByRole('heading', { name: 'These parts define the robot body.' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '← Back to requirements' }))
    expect(screen.getByRole('heading', { name: 'Review the choices that shape the result' })).toBeInTheDocument()
  })
})
