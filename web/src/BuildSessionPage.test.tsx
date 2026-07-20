import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { BuildSessionPage } from './BuildSessionPage'

afterEach(() => vi.unstubAllGlobals())

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
    expect(screen.getByLabelText('What should Ariad help you make?')).toHaveValue('Make a cute two-servo robot with long rotating side limbs that can recover when it falls. Design it as separate, serviceable parts with accessible fasteners.')
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
    expect(screen.getByText('Which exact servo, camera, compute board, and battery should define the enclosure?')).toBeInTheDocument()
    expect(screen.queryByText(/configure GPT/i)).not.toBeInTheDocument()
    expect(screen.getByText(/does not create CAD yet/i)).toBeInTheDocument()
  })

  it('records one explicit approval without forcing a second confirmation screen', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/v1/session')) return response({ schema_version: '1.19.0', session_token: 'browser-secret' })
      if (url.endsWith('/api/v1/intake')) return response(intake)
      if (url.endsWith('/api/v1/projects') && init?.method === 'POST') return response({ project_id: 'project_demo', title: 'Robot', prompt: 'Make a robot.' })
      if (url.endsWith('/draft')) return response({ status: 'ready_for_confirmation', missing_fields: [] })
      return response({ project_id: 'project_demo', job_id: 'job_demo', revision_id: 'rev_demo', evidence_level: 'R0' })
    }))
    render(<MemoryRouter><BuildSessionPage /></MemoryRouter>)

    fireEvent.change(screen.getByLabelText('What should Ariad help you make?'), { target: { value: 'Make a robot.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Approve and continue' }))

    expect(await screen.findByRole('heading', { name: 'Your idea is ready for the Design stage' })).toBeInTheDocument()
    expect(screen.getByText(/CAD is still absent/i)).toBeInTheDocument()
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
      if (url.endsWith('/demo/robot-cad/manifest.json')) return response({ artifact_kind: 'prototype_geometry', design_source_version: '0.2.0', part_count: 1, claim_boundary: 'Prototype only.', parts: [{ part_id: 'front_shell', step: 'front_shell.step', stl: 'front_shell.stl', glb: 'front_shell.glb', glb_sha256: 'b'.repeat(64), kernel_valid: true, solid_count: 1, volume_mm3: 1000 }] })
      if (url.endsWith('/demo/robot-cad/front_shell.glb')) return new Response(new ArrayBuffer(0), { status: 200 })
      throw new Error(`Unexpected request: ${url}`)
    }))
    render(<MemoryRouter><BuildSessionPage /></MemoryRouter>)

    fireEvent.change(screen.getByLabelText('What should Ariad help you make?'), { target: { value: 'Make a robot.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Approve and continue' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Prepare Design plan' }))

    expect(await screen.findByText('Local fallback')).toBeInTheDocument()
    expect(screen.getByDisplayValue(/Decompose the robot into separately manufactured/)).toBeInTheDocument()
    expect(screen.getByText(/does not run generated code or create R1/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save Design plan' }))
    expect(await screen.findByRole('heading', { name: 'Inspect the robot CAD parts' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Front Shell.*Valid solid/i })).toBeInTheDocument()
    expect(screen.getByText(/still needs per-part dimensions/i)).toBeInTheDocument()
  })
})
