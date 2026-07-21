import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ProjectsPage } from './ProjectsPage'

afterEach(() => vi.restoreAllMocks())

describe('ProjectsPage', () => {
  it('labels confirmed intent without claiming Brief or fabrication evidence', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const body = String(input).endsWith('/api/v1/session')
        ? { schema_version: '1.18.0', session_token: 'browser-secret' }
        : { schema_version: '1.18.0', projects: [{ schema_version: '1.0.0', project_id: 'project_12345678901234567890123456789012', title: 'Floating airship', prompt: 'A 120 mm display model', prompt_sha256: 'a'.repeat(64), confirmed_at: '2026-07-18T00:00:00Z', confirmed_by: 'user', status: 'intent_confirmed', evidence_mode: 'user_confirmed', brief_evidence_level: null, fabrication_started: false, hardware_actions: false }], fabrication_started: false, hardware_actions: false }
      return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    render(<MemoryRouter><ProjectsPage /></MemoryRouter>)
    await screen.findByText('Floating airship')
    expect(screen.getByText('Ready to continue')).toBeInTheDocument()
    expect(screen.getByText('Planning')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open saved brief' })).toHaveAttribute('href', '/projects/project_12345678901234567890123456789012')
  })
})
