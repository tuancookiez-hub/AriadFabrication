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
      if (url.endsWith('/api/v1/session')) body = { schema_version: '1.14.0', session_token: 'browser-secret' }
      else if (init?.method === 'PUT') body = { schema_version: '1.0.0', project_id: 'project_12345678901234567890123456789012', name: 'Airship', purpose: null, part_type: null, size_x_mm: null, size_y_mm: null, size_z_mm: null, material: null, tolerance_mm: null, support_policy: null, manufacturing_process: 'FDM', safety_class: 'general', updated_at: '2026-07-18T00:00:00Z', status: 'needs_input', missing_fields: ['purpose', 'size_x_mm'], brief_evidence_level: null, fabrication_started: false, hardware_actions: false }
      else body = { schema_version: '1.14.0', project: { schema_version: '1.0.0', project_id: 'project_12345678901234567890123456789012', title: 'Floating airship', prompt: 'A model', prompt_sha256: 'a'.repeat(64), confirmed_at: '2026-07-18T00:00:00Z', confirmed_by: 'user', status: 'intent_confirmed', evidence_mode: 'user_confirmed', brief_evidence_level: null, fabrication_started: false, hardware_actions: false }, draft: null, fabrication_started: false, hardware_actions: false }
      return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    render(<MemoryRouter initialEntries={['/projects/project_12345678901234567890123456789012']}><Routes><Route path="/projects/:projectId" element={<ProjectClarifyPage />} /></Routes></MemoryRouter>)
    await screen.findByText('Floating airship')
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Airship' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save clarification draft' }))
    await screen.findByText('Draft saved. Still missing: purpose, size_x_mm.')
    expect(screen.getByText('Unknowns stay visible. Saving this form does not confirm the PartSpec or start fabrication.')).toBeInTheDocument()
  })
})
