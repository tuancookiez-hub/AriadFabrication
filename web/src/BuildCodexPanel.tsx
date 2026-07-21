import { type FormEvent, useEffect, useRef, useState } from 'react'

import { cancelCodexTurn, getCodexEvents, startCodexTurn } from './api'

type Message = { id: string; role: 'user' | 'assistant'; text: string }

export function BuildCodexPanel({ available, context, projectId, sessionToken, onClose }: { available: boolean; context: string; projectId: string; sessionToken: string | null; onClose: () => void }) {
  const [prompt, setPrompt] = useState(context)
  const [messages, setMessages] = useState<Message[]>([])
  const [activeTurn, setActiveTurn] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const sequence = useRef(0)

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
              const index = current.findIndex((message) => message.id === event.turn_id)
              if (index < 0) return [...current, { id: event.turn_id, role: 'assistant', text: event.text }]
              return current.map((message, itemIndex) => itemIndex === index ? { ...message, text: message.text + event.text } : message)
            })
          }
          if (['turn_completed', 'turn_failed', 'turn_cancelled'].includes(event.event_type)) {
            setActiveTurn(null)
            if (event.event_type === 'turn_failed') setError(event.text || 'Codex could not complete this review.')
          }
        }
        if (!stopped && result.active_turn_id) window.setTimeout(poll, 400)
      } catch (reason) {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : 'Codex review could not load.')
          setActiveTurn(null)
        }
      }
    }
    void poll()
    return () => { stopped = true; controller.abort() }
  }, [activeTurn, sessionToken])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!available || !sessionToken || !prompt.trim() || activeTurn) return
    const visiblePrompt = prompt.trim()
    const contextualPrompt = `You are assisting inside Ariad's guided fabrication build for project ${projectId}. ${visiblePrompt} Explain the practical decision in beginner-friendly language. Preserve Ariad's digital-only evidence boundary and do not claim physical validation or execute hardware.`
    setMessages((current) => [...current, { id: `user-${Date.now()}`, role: 'user', text: visiblePrompt }])
    setPrompt('')
    setError(null)
    try {
      const result = await startCodexTurn(contextualPrompt, sessionToken)
      setActiveTurn(result.turn_id)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Codex review could not start.')
    }
  }

  async function cancel() {
    if (!sessionToken) return
    try { await cancelCodexTurn(sessionToken) } catch (reason) { setError(reason instanceof Error ? reason.message : 'Codex could not stop.') }
  }

  return <aside className="build-codex-panel" aria-label="Codex build assistant">
    <header><div><span className="conversation-avatar">C</span><div><strong>Ask Codex without leaving the build</strong><small>Project context is attached automatically.</small></div></div><button aria-label="Close Codex assistant" onClick={onClose} type="button">×</button></header>
    <div className="build-codex-messages" aria-live="polite">
      {messages.length === 0 ? <p>{available ? 'Ask about the current component, model, warning, or next decision. Your build stage will remain exactly where it is.' : 'Codex is not connected in this demo session. The build remains usable, and this panel will become available when the local Codex process is started.'}</p> : null}
      {messages.map((message) => <article className={`chat-message chat-message-${message.role}`} key={message.id}><strong>{message.role === 'user' ? 'You' : 'Codex'}</strong><p>{message.text}</p></article>)}
      {activeTurn ? <div className="codex-thinking" role="status"><i /> Codex is reviewing this stage…</div> : null}
      {error ? <div className="chat-error" role="alert">{error}</div> : null}
    </div>
    <form onSubmit={submit}><label htmlFor="build-codex-prompt">What should Codex help with?</label><textarea disabled={!available} id="build-codex-prompt" maxLength={16_384} onChange={(event) => setPrompt(event.target.value)} rows={3} value={prompt} /><div><small>Advisory only · you approve any design change</small>{activeTurn ? <button className="stop-action" onClick={cancel} type="button">Stop</button> : <button className="primary-action" disabled={!available || !sessionToken || !prompt.trim()} type="submit">Ask Codex</button>}</div></form>
  </aside>
}
