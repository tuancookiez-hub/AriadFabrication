import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { CodexChatPage } from './CodexChatPage'

afterEach(() => vi.restoreAllMocks())

describe('CodexChatPage', () => {
  it('opens an R0 project in explicit Design proposal mode', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      const body = url.endsWith('/api/v1/codex/status')
        ? { schema_version: '1.19.0', state: 'ready', available: true, conversation_available: true, authenticated: true, executable: 'codex.exe', version: '0.145.0', model: null, auth_mode: 'chatgpt', reason: 'Ready.' }
        : { schema_version: '1.19.0', session_token: 'browser-secret' }
      return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    const projectId = 'project_12345678901234567890123456789012'
    render(<MemoryRouter initialEntries={[`/chat?project=${projectId}`]}><CodexChatPage /></MemoryRouter>)
    await screen.findByText('Design proposal mode')
    expect((screen.getByLabelText('Message Codex') as HTMLTextAreaElement).value).toContain(projectId)
    expect(screen.getByRole('link', { name: 'Return to the Design workspace' })).toHaveAttribute('href', `/projects/${projectId}`)
    expect(screen.getByText('Codex can propose fields for review; Ariad will not save them automatically.')).toBeInTheDocument()
  })

  it('streams a local Codex reply through the authenticated browser session', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      let body: unknown
      if (url.endsWith('/api/v1/codex/status')) body = { schema_version: '1.18.0', state: 'ready', available: true, conversation_available: true, authenticated: true, executable: 'codex.exe', version: '0.144.5', model: null, auth_mode: 'chatgpt', reason: 'Ready for a local read-only conversation.' }
      else if (url.endsWith('/api/v1/session')) body = { schema_version: '1.18.0', session_token: 'browser-secret' }
      else if (url.endsWith('/api/v1/codex/turns')) body = { schema_version: '1.18.0', turn_id: 'turn_demo', accepted: true, tools_registered: 4 }
      else if (url.endsWith('/api/v1/projects')) body = { schema_version: '1.18.0', project_id: 'project_12345678901234567890123456789012', title: 'Design a small airship.', prompt: 'Design a small airship.', prompt_sha256: 'a'.repeat(64), confirmed_at: '2026-07-18T00:00:00Z', confirmed_by: 'user', status: 'intent_confirmed', evidence_mode: 'user_confirmed', brief_evidence_level: null, fabrication_started: false, hardware_actions: false }
      else body = { schema_version: '1.18.0', events: [{ contract_version: '1.1.0', sequence: 1, turn_id: 'turn_demo', event_type: 'tool_started', text: '', tool_name: 'ariad.capture_idea' }, { contract_version: '1.1.0', sequence: 2, turn_id: 'turn_demo', event_type: 'tool_completed', text: '', tool_name: 'ariad.capture_idea' }, { contract_version: '1.1.0', sequence: 3, turn_id: 'turn_demo', event_type: 'assistant_text_delta', text: 'Let us define the purpose first.', tool_name: null }, { contract_version: '1.1.0', sequence: 4, turn_id: 'turn_demo', event_type: 'turn_completed', text: '', tool_name: null }], next_sequence: 4, active_turn_id: null, tools_registered: 4 }
      return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })

    render(<MemoryRouter><CodexChatPage /></MemoryRouter>)
    await screen.findByText('Codex conversation ready')
    fireEvent.change(screen.getByLabelText('Message Codex'), { target: { value: 'Design a small airship.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    await screen.findByText('Let us define the purpose first.')
    expect(screen.getByText('ariad.capture_idea')).toBeInTheDocument()
    expect(screen.getByText('completed')).toBeInTheDocument()
    expect(screen.getByText('This saves a user-confirmed intent only. It is not an R0 Brief and starts no fabrication.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and save intent' }))
    await screen.findByText('Project intent saved')
    expect(screen.getByText('No Brief evidence or fabrication run exists yet.')).toBeInTheDocument()
    expect(screen.getAllByText('Design a small airship.')).toHaveLength(2)
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/codex/turns',
      expect.objectContaining({ headers: expect.objectContaining({ 'X-Ariad-Session': 'browser-secret' }) }),
    ))
  })
})
