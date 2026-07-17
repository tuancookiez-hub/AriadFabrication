import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { CodexChatPage } from './CodexChatPage'

afterEach(() => vi.restoreAllMocks())

describe('CodexChatPage', () => {
  it('streams a local Codex reply through the authenticated browser session', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      let body: unknown
      if (url.endsWith('/api/v1/codex/status')) body = { schema_version: '1.12.0', state: 'ready', available: true, conversation_available: true, authenticated: true, executable: 'codex.exe', version: '0.144.5', model: null, auth_mode: 'chatgpt', reason: 'Ready for a local read-only conversation.' }
      else if (url.endsWith('/api/v1/session')) body = { schema_version: '1.12.0', session_token: 'browser-secret' }
      else if (url.endsWith('/api/v1/codex/turns')) body = { schema_version: '1.12.0', turn_id: 'turn_demo', accepted: true, tools_registered: 3 }
      else body = { schema_version: '1.12.0', events: [{ contract_version: '1.1.0', sequence: 1, turn_id: 'turn_demo', event_type: 'tool_started', text: '', tool_name: 'ariad.capture_idea' }, { contract_version: '1.1.0', sequence: 2, turn_id: 'turn_demo', event_type: 'tool_completed', text: '', tool_name: 'ariad.capture_idea' }, { contract_version: '1.1.0', sequence: 3, turn_id: 'turn_demo', event_type: 'assistant_text_delta', text: 'Let us define the purpose first.', tool_name: null }, { contract_version: '1.1.0', sequence: 4, turn_id: 'turn_demo', event_type: 'turn_completed', text: '', tool_name: null }], next_sequence: 4, active_turn_id: null, tools_registered: 3 }
      return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })

    render(<MemoryRouter><CodexChatPage /></MemoryRouter>)
    await screen.findByText('Codex conversation ready')
    fireEvent.change(screen.getByLabelText('Message Codex'), { target: { value: 'Design a small airship.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    await screen.findByText('Let us define the purpose first.')
    expect(screen.getByText('ariad.capture_idea')).toBeInTheDocument()
    expect(screen.getByText('completed')).toBeInTheDocument()
    expect(screen.getByText('Design a small airship.')).toBeInTheDocument()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/codex/turns',
      expect.objectContaining({ headers: expect.objectContaining({ 'X-Ariad-Session': 'browser-secret' }) }),
    ))
  })
})
