import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ProjectClarifyPage } from './ProjectClarifyPage'

afterEach(() => vi.restoreAllMocks())

describe('ProjectClarifyPage', () => {
  it('saves nullable unknowns without claiming R0 evidence', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      let body: unknown
      if (url.endsWith('/api/v1/session')) body = { schema_version: '1.16.0', session_token: 'browser-secret' }
      else if (init?.method === 'PUT') body = { schema_version: '1.0.0', project_id: 'project_12345678901234567890123456789012', name: 'Airship', purpose: null, part_type: null, size_x_mm: null, size_y_mm: null, size_z_mm: null, material: null, tolerance_mm: null, support_policy: null, manufacturing_process: 'FDM', safety_class: 'general', updated_at: '2026-07-18T00:00:00Z', status: 'needs_input', missing_fields: ['purpose', 'size_x_mm'], brief_evidence_level: null, fabrication_started: false, hardware_actions: false }
      else body = { schema_version: '1.16.0', project: { schema_version: '1.0.0', project_id: 'project_12345678901234567890123456789012', title: 'Floating airship', prompt: 'A model', prompt_sha256: 'a'.repeat(64), confirmed_at: '2026-07-18T00:00:00Z', confirmed_by: 'user', status: 'intent_confirmed', evidence_mode: 'user_confirmed', brief_evidence_level: null, fabrication_started: false, hardware_actions: false }, draft: null, brief: null, fabrication_started: false, hardware_actions: false }
      return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    render(<MemoryRouter initialEntries={['/projects/project_12345678901234567890123456789012']}><Routes><Route path="/projects/:projectId" element={<ProjectClarifyPage />} /></Routes></MemoryRouter>)
    await screen.findByText('Floating airship')
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Airship' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save clarification draft' }))
    await screen.findByText('Draft saved. Still missing: purpose, size_x_mm.')
    expect(screen.getByText('Unknowns stay visible. Saving this form does not confirm the PartSpec or start fabrication.')).toBeInTheDocument()
  })

  it('requires a separate user approval before creating the R0 Brief', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      const draft = { schema_version: '1.0.0', project_id: 'project_12345678901234567890123456789012', name: 'Airship', purpose: 'Desk display', part_type: 'decorative model', size_x_mm: 120, size_y_mm: 45, size_z_mm: 35, material: 'PLA', tolerance_mm: 0.2, support_policy: 'allowed', manufacturing_process: 'FDM', safety_class: 'general', updated_at: '2026-07-18T00:00:00Z', status: 'ready_for_confirmation', missing_fields: [], brief_evidence_level: null, fabrication_started: false, hardware_actions: false }
      let body: unknown
      if (url.endsWith('/api/v1/session')) body = { schema_version: '1.16.0', session_token: 'browser-secret' }
      else if (init?.method === 'POST') body = { schema_version: '1.0.0', project_id: draft.project_id, job_id: 'job_demo', revision_id: 'rev_demo', draft_sha256: 'a'.repeat(64), confirmed_at: '2026-07-18T00:01:00Z', confirmed_by: 'user', evidence_level: 'R0', status: 'ready_for_design', fabrication_started: false, hardware_actions: false }
      else if (init?.method === 'PUT') body = { schema_version: '1.0.0', project_id: draft.project_id, job_id: 'job_demo', revision_id: 'rev_demo', brief_draft_sha256: 'a'.repeat(64), lane: 'organic_mesh', geometry_strategy: 'Build a watertight decorative hull.', critical_features: ['Stable base'], assembly_interfaces: [], constraints: ['Confirmed envelope'], unresolved_questions: [], updated_at: '2026-07-18T00:02:00Z', authored_by: 'user', status: 'planning_complete', evidence_mode: 'planning_only', design_evidence_level: null, cad_generated: false, fabrication_started: false, hardware_actions: false }
      else body = { schema_version: '1.16.0', project: { schema_version: '1.0.0', project_id: draft.project_id, title: 'Floating airship', prompt: 'A model', prompt_sha256: 'a'.repeat(64), confirmed_at: '2026-07-18T00:00:00Z', confirmed_by: 'user', status: 'intent_confirmed', evidence_mode: 'user_confirmed', brief_evidence_level: null, fabrication_started: false, hardware_actions: false }, draft, brief: null, design_plan: null, fabrication_started: false, hardware_actions: false }
      return new Response(JSON.stringify(body), { status: init?.method === 'POST' ? 201 : 200, headers: { 'Content-Type': 'application/json' } })
    })
    render(<MemoryRouter initialEntries={['/projects/project_12345678901234567890123456789012']}><Routes><Route path="/projects/:projectId" element={<ProjectClarifyPage />} /></Routes></MemoryRouter>)
    const confirm = await screen.findByRole('button', { name: 'Confirm PartSpec and create R0 Brief' })
    expect(confirm).toBeDisabled()
    fireEvent.click(screen.getByLabelText('I reviewed these requirements and approve them for Design.'))
    fireEvent.click(confirm)
    await screen.findByText('R0 Brief confirmed. This project is ready for Design. Fabrication has not started.')
    expect(screen.getByRole('link', { name: 'Open the R0 Journey' })).toHaveAttribute('href', '/jobs/job_demo/revisions/rev_demo')
    fireEvent.change(screen.getByLabelText('Design lane'), { target: { value: 'organic_mesh' } })
    fireEvent.change(screen.getByLabelText('Geometry strategy'), { target: { value: 'Build a watertight decorative hull.' } })
    fireEvent.change(screen.getByLabelText('Critical features'), { target: { value: 'Stable base' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save Design plan' }))
    await screen.findByText('Design plan saved as planning complete. CAD has not been generated.')
    expect(screen.getByText('Planning only · no R1 evidence')).toBeInTheDocument()
  })
})
