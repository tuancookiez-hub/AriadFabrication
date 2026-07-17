import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { NewIdeaPage } from './NewIdeaPage'

afterEach(() => vi.restoreAllMocks())

describe('NewIdeaPage', () => {
  it('captures an imaginative prompt without claiming model inference or execution', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({
        schema_version: '1.10.0',
        intake: { schema_version: '1.0.0', intake_id: 'intake_demo', prompt: 'A floating airship', prompt_sha256: 'a'.repeat(64), hardware_actions: false },
        provider: { provider_id: 'openai_gpt_5_6_intent', model: 'gpt-5.6-sol', configured: false, evidence_mode: 'unavailable', reason: 'No API credential is configured.' },
        route: { schema_version: '1.0.0', intake_id: 'intake_demo', prompt_sha256: 'a'.repeat(64), lane: 'planning_only', status: 'needs_input', summary: 'A floating airship', reason: 'Provider unavailable.', questions: ['Configure GPT-5.6.'], assumptions: [], part_spec: null, available_targets: [], evidence_mode: 'model_proposal', hardware_actions: false, physical_validation: false, metadata: {} },
        persisted: false,
        executed: false,
        claim_boundary: 'Intent captured only. Nothing executed.',
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    )

    render(<MemoryRouter><NewIdeaPage /></MemoryRouter>)
    fireEvent.change(screen.getByLabelText('Your fabrication idea'), { target: { value: 'A floating airship' } })
    fireEvent.click(screen.getByRole('button', { name: 'Begin journey' }))

    await screen.findByText('Idea captured')
    expect(screen.getByText('Unavailable')).toBeInTheDocument()
    expect(screen.getByText('Not run')).toBeInTheDocument()
    expect(screen.getByText('Intent captured only. Nothing executed.')).toBeInTheDocument()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/v1/intake', expect.objectContaining({ method: 'POST' })))
    expect(JSON.parse(String((fetchMock.mock.calls[0]?.[1] as RequestInit).body))).toEqual({ prompt: 'A floating airship' })
  })
})
