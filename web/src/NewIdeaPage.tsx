import { type FormEvent, useState } from 'react'
import { Link } from 'react-router-dom'

import { captureIdea } from './api'
import type { IntakeResponse } from './types'

export function NewIdeaPage() {
  const [prompt, setPrompt] = useState('')
  const [result, setResult] = useState<IntakeResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      setResult(await captureIdea(prompt))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The idea could not be captured.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <section className="idea-hero">
        <p className="eyebrow">Start with intent, not geometry</p>
        <h1 data-route-heading tabIndex={-1}>What do you want to make?</h1>
        <p>
          Describe any useful, decorative, mechanical, robotic, planting, or experimental idea.
          Ariad captures the request first, then exposes what the current pipeline can and cannot do.
        </p>
      </section>
      <section className="idea-workspace" aria-labelledby="idea-form-heading">
        <form className="idea-form" onSubmit={submit}>
          <div>
            <p className="eyebrow">Stage 1 · Describe the need</p>
            <h2 id="idea-form-heading">Plain-language request</h2>
          </div>
          <label htmlFor="idea-prompt">Your fabrication idea</label>
          <textarea
            id="idea-prompt"
            maxLength={16_384}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="Example: Create a small floating-airship desk model with a display stand."
            required
            rows={8}
            value={prompt}
          />
          <div className="idea-form-footer">
            <small>{new TextEncoder().encode(prompt).length.toLocaleString()} / 16,384 UTF-8 bytes</small>
            <button className="primary-action" disabled={busy || prompt.trim().length === 0} type="submit">
              {busy ? 'Capturing…' : 'Begin journey'}
            </button>
          </div>
        </form>
        <aside className="capability-card" aria-label="Current capability boundary">
          <p className="eyebrow">Current system boundary</p>
          <h2>Universal intake, gated execution</h2>
          <ol>
            <li><strong>Capture</strong><span>Available for any bounded prompt</span></li>
            <li><strong>Clarify</strong><span>GPT-5.6 needs a local API credential</span></li>
            <li><strong>Generate</strong><span>Only registered benchmark execution is proven</span></li>
            <li><strong>Print</strong><span>Disconnected; no physical claims</span></li>
          </ol>
        </aside>
      </section>
      {error ? <section className="idea-result error-panel" role="alert"><strong>Capture failed</strong><p>{error}</p></section> : null}
      {result ? (
        <section className="idea-result" aria-live="polite">
          <div className="result-heading">
            <div><p className="eyebrow">Idea captured</p><h2>{result.route.summary}</h2></div>
            <span className="status-badge status-needs_input">{result.route.status.replaceAll('_', ' ')}</span>
          </div>
          <div className="truth-grid">
            <article><span>GPT-5.6</span><strong>{result.provider.configured ? 'Configured' : 'Unavailable'}</strong><p>{result.provider.reason}</p></article>
            <article><span>Route</span><strong>{result.route.lane.replaceAll('_', ' ')}</strong><p>{result.route.reason}</p></article>
            <article><span>Execution</span><strong>{result.executed ? 'Executed' : 'Not run'}</strong><p>{result.claim_boundary}</p></article>
          </div>
          {result.route.questions.length > 0 ? <div className="next-question"><strong>What Ariad needs next</strong><p>{result.route.questions[0]}</p></div> : null}
          <Link className="secondary-action" to="/">Explore existing evidence journeys</Link>
        </section>
      ) : null}
    </>
  )
}
