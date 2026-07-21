import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AssemblyPage } from './AssemblyPage'

afterEach(() => vi.unstubAllGlobals())

describe('AssemblyPage', () => {
  it('separates the visual concept from assembly evidence', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      schema_version: '1.19.0', contract_version: '1.0.0', assembly_id: 'robot',
      name: 'Ariad Two-Servo Robot V1', purpose: 'A serviceable robot.', status: 'draft',
      parts: [{ part_id: 'shell', name: 'Front shell', role: 'Protect electronics.', quantity: 1, separately_manufactured: true, manufacturing_process: 'FDM', material: 'PETG', notes: 'Split unresolved.' }],
      component_envelopes: [{ component_id: 'servo', name: 'Servo', quantity: 2, evidence: 'placeholder', dimensions_mm: { length: 24, width: 14, height: 30 }, mass_g: 9, source: 'Replace with official drawing.' }],
      interfaces: [{ interface_id: 'joint', name: 'Rotary joint', kind: 'rotating', participants: ['part:shell', 'component:servo'], clearance_mm: 0.5, axis: 'X', requirements: ['Avoid collision.'] }],
      assembly_constraints: ['Parts are separate.'], unresolved_questions: ['Which servo?'],
      claim_boundary: 'No CAD, fit, simulation, or physical evidence.', evidence_mode: 'planning_fixture',
      cad_generated: false, simulation_run: false, hardware_actions: false, physical_validation: false,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })))

    render(<AssemblyPage />)

    expect(await screen.findByRole('heading', { name: 'Ariad Two-Servo Robot V1' })).toBeInTheDocument()
    expect(screen.getByText('Pi and servo architecture precedes the shell · visual intent, not physical fit evidence.')).toBeInTheDocument()
    expect(screen.getByText('CAD not generated')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Build it as an assembly, not one mesh' })).toBeInTheDocument()
    expect(screen.getByText('Which servo?')).toBeInTheDocument()
  })
})
