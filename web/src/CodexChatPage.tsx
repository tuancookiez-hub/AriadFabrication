import { type FormEvent, useEffect, useRef, useState } from 'react'

import {
  cancelCodexTurn,
  getBrowserSession,
  getCodexEvents,
  getLocalCodexStatus,
  startCodexTurn,
} from './api'
import type { LocalCodexStatus } from './types'

type Message = { id: string; role: 'user' | 'assistant'; text: string }

export function CodexChatPage() {
  const [status, setStatus] = useState<LocalCodexStatus | null>(null)
  const [sessionToken, setSessionToken] = useState<string | null>(null)
  const [prompt, setPrompt] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [activeTurn, setActiveTurn] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const sequence = useRef(0)

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([getLocalCodexStatus(controller.signal), getBrowserSession(controller.signal)])
      .then(([nextStatus, session]) => {
        setStatus(nextStatus)
        setSessionToken(session.session_token)
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : 'Local Codex status could not load.')
        }
      })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!activeTurn || !sessionToken) return
    let stopped = false
    const controller = new AbortController()

    async function poll() {
      if (stopped) return
      try {
        const result = await getCodexEvents(sequence.current, sessionToken!, controller.signal)
        sequence.current = result.next_sequence
        for (const event of result.events) {
          if (event.event_type === 'assistant_text_delta') {
            setMessages((current) => {
              const existing = current.findIndex((item) => item.id === event.turn_id)
              if (existing < 0) {
                return [...current, { id: event.turn_id, role: 'assistant', text: event.text }]
              }
              return current.map((item, index) =>
                index === existing ? { ...item, text: item.text + event.text } : item,
              )
            })
          }
          if (['turn_completed', 'turn_failed', 'turn_cancelled'].includes(event.event_type)) {
            setActiveTurn(null)
            if (event.event_type === 'turn_failed') setError(event.text || 'Codex turn failed.')
          }
        }
        if (!stopped && result.active_turn_id) window.setTimeout(poll, 400)
        if (!result.active_turn_id) setActiveTurn(null)
      } catch (reason) {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : 'Codex events could not load.')
          setActiveTurn(null)
        }
      }
    }
    void poll()
    return () => {
      stopped = true
      controller.abort()
    }
  }, [activeTurn, sessionToken])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!sessionToken || !status?.conversation_available || !prompt.trim()) return
    const text = prompt.trim()
    setPrompt('')
    setError(null)
    setMessages((current) => [...current, { id: `user-${Date.now()}`, role: 'user', text }])
    try {
      const result = await startCodexTurn(text, sessionToken)
      setActiveTurn(result.turn_id)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Codex turn could not start.')
    }
  }

  async function cancel() {
    if (!sessionToken) return
    try {
      await cancelCodexTurn(sessionToken)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Codex cancellation failed.')
    }
  }

  const ready = status?.conversation_available === true && sessionToken !== null

  return (
    <>
      <section className="chat-hero">
        <p className="eyebrow">Local Codex fabrication agent</p>
        <h1 data-route-heading tabIndex={-1}>Talk through what you want to make.</h1>
        <p>
          This first connection is conversational and read-only. Codex has no Ariad fabrication
          tools yet and cannot generate CAD, run validation, slice, or contact hardware.
        </p>
      </section>
      <section className="chat-layout">
        <div className="chat-panel">
          <div className="chat-status" role="status">
            <i />
            <span>
              <strong>{ready ? 'Codex conversation ready' : 'Codex conversation unavailable'}</strong>
              <small>{status?.reason ?? 'Checking the local runtime...'}</small>
            </span>
          </div>
          <div className="message-list" aria-live="polite" aria-label="Conversation messages">
            {messages.length === 0 ? (
              <div className="chat-empty">
                Try describing a project, its purpose, approximate size, and whether it is decorative
                or functional.
              </div>
            ) : null}
            {messages.map((message) => (
              <article className={`chat-message chat-message-${message.role}`} key={message.id}>
                <strong>{message.role === 'user' ? 'You' : 'Codex'}</strong>
                <p>{message.text}</p>
              </article>
            ))}
          </div>
          {error ? <div className="chat-error" role="alert">{error}</div> : null}
          <form className="chat-composer" onSubmit={submit}>
            <label htmlFor="codex-prompt">Message Codex</label>
            <textarea
              disabled={!ready || activeTurn !== null}
              id="codex-prompt"
              maxLength={16_384}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="Describe something you want to fabricate..."
              rows={4}
              value={prompt}
            />
            <div>
              <small>Local session · read-only · zero fabrication tools</small>
              {activeTurn ? (
                <button className="stop-action" onClick={cancel} type="button">Stop Codex</button>
              ) : (
                <button className="primary-action" disabled={!ready || !prompt.trim()} type="submit">Send</button>
              )}
            </div>
          </form>
        </div>
        <aside className="chat-boundary">
          <p className="eyebrow">Authority right now</p>
          <h2>Conversation only</h2>
          <dl>
            <div><dt>GPT model</dt><dd>{status?.conversation_available ? 'Local Codex default' : 'Unavailable'}</dd></div>
            <div><dt>Ariad tools</dt><dd>0 registered</dd></div>
            <div><dt>Workspace</dt><dd>Read-only and empty</dd></div>
            <div><dt>Hardware</dt><dd>Disconnected</dd></div>
          </dl>
          <p>CAD and pipeline controls stay locked until their isolation and evidence gates pass.</p>
        </aside>
      </section>
    </>
  )
}
