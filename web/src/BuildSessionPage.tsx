import { type FormEvent, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { AssemblyBlueprint } from './AssemblyBlueprint'
import {
  ApiError,
  captureIdea,
  confirmProjectBrief,
  createProjectIntent,
  getBrowserSession,
  getProjectDesignProposal,
  saveProjectDesignPlan,
  saveProjectDraft,
} from './api'
import type { IntakeResponse, ProjectBrief, ProjectDesignPlanRequest, ProjectDraftRequest, ProjectIntent } from './types'

type SessionStep = 'describe' | 'review' | 'approve' | 'ready' | 'design' | 'planned'

function suggestedTitle(prompt: string): string {
  const first = prompt.trim().split(/[.!?\n]/)[0]?.trim() ?? 'New fabrication project'
  return first.slice(0, 80) || 'New fabrication project'
}

function suggestedPartType(prompt: string): string {
  const value = prompt.toLowerCase()
  if (value.includes('robot')) return 'multi-part robot enclosure'
  if (value.includes('mount') || value.includes('bracket')) return 'functional mounting part'
  if (value.includes('model') || value.includes('figure')) return 'display model'
  return 'fabricated product'
}

function suggestedDraft(prompt: string): ProjectDraftRequest {
  const robot = prompt.toLowerCase().includes('robot')
  return {
    name: suggestedTitle(prompt),
    purpose: prompt.trim(),
    part_type: suggestedPartType(prompt),
    size_x_mm: robot ? 110 : 100,
    size_y_mm: robot ? 70 : 100,
    size_z_mm: robot ? 100 : 100,
    material: 'PETG',
    tolerance_mm: 0.3,
    support_policy: 'avoid',
    manufacturing_process: 'FDM',
    safety_class: 'general',
  }
}

function fallbackDesignPlan(prompt: string): ProjectDesignPlanRequest {
  const robot = prompt.toLowerCase().includes('robot')
  return {
    lane: 'functional_parametric',
    geometry_strategy: robot
      ? 'Decompose the robot into separately manufactured parametric parts around verified component envelopes, then validate each part and the complete assembly independently.'
      : 'Create dimension-driven parametric geometry from the approved envelope and keep every critical interface editable.',
    critical_features: robot
      ? ['Serviceable body shell', 'Two aligned rotating side joints', 'Removable electronics carrier', 'Unobstructed camera opening']
      : ['Approved overall envelope', 'Critical fit interface', 'Minimum wall thickness'],
    assembly_interfaces: robot
      ? ['Shell to electronics tray', 'Left and right servo-to-limb joints', 'Camera to bezel', 'Service panel access']
      : ['Primary mating interface'],
    constraints: ['FDM manufacturing', 'Avoid supports where practical', 'Preserve user-approved dimensions and evidence boundaries'],
    unresolved_questions: robot
      ? ['Confirm exact servo and horn', 'Confirm camera module', 'Confirm compute board and battery', 'Confirm fastener strategy']
      : ['Confirm the exact real-world object that defines the critical fit'],
  }
}

const stageLabels = ['Describe', 'Confirm', 'Design', 'Verify', 'Simulate', 'Package']

export function BuildSessionPage() {
  const [step, setStep] = useState<SessionStep>('describe')
  const [prompt, setPrompt] = useState('')
  const [intake, setIntake] = useState<IntakeResponse | null>(null)
  const [draft, setDraft] = useState<ProjectDraftRequest>(() => suggestedDraft(''))
  const [token, setToken] = useState<string | null>(null)
  const [project, setProject] = useState<ProjectIntent | null>(null)
  const [brief, setBrief] = useState<ProjectBrief | null>(null)
  const [designPlan, setDesignPlan] = useState<ProjectDesignPlanRequest>(() => fallbackDesignPlan(''))
  const [planSource, setPlanSource] = useState<'codex' | 'local' | null>(null)
  const [approved, setApproved] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getBrowserSession(controller.signal).then((session) => setToken(session.session_token)).catch(() => setToken(null))
    return () => controller.abort()
  }, [])

  const activeIndex = useMemo(() => step === 'describe' ? 0 : step === 'review' || step === 'approve' ? 1 : step === 'ready' || step === 'design' ? 2 : 3, [step])
  const localFallback = intake?.provider.configured === false
  const reviewSummary = localFallback ? suggestedPartType(prompt) : intake?.route.summary
  const reviewReason = localFallback
    ? 'Ariad prepared editable local defaults. No model classified this request, so exact product decisions stay visible.'
    : intake?.route.reason
  const reviewQuestion = localFallback
    ? (prompt.toLowerCase().includes('robot')
        ? 'Which exact servo, camera, compute board, and battery should define the enclosure?'
        : 'Which exact real-world object or component should define the critical fit?')
    : intake?.route.questions[0]

  async function understand(event: FormEvent) {
    event.preventDefault()
    setBusy(true); setError(null)
    try {
      const result = await captureIdea(prompt)
      setIntake(result); setDraft(suggestedDraft(prompt)); setStep('review')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Ariad could not understand the request.')
    } finally { setBusy(false) }
  }

  function text(name: keyof ProjectDraftRequest, value: string) {
    setDraft((current) => ({ ...current, [name]: value.trim() ? value : null }))
  }
  function number(name: keyof ProjectDraftRequest, value: string) {
    setDraft((current) => ({ ...current, [name]: value ? Number(value) : null }))
  }

  async function prepareBrief() {
    if (!token) { setError('The local Ariad session is unavailable.'); return }
    setBusy(true); setError(null)
    try {
      const created = await createProjectIntent(draft.name ?? suggestedTitle(prompt), prompt, token)
      const saved = await saveProjectDraft(created.project_id, draft, token)
      setProject(created)
      if (saved.status !== 'ready_for_confirmation') {
        setError(`Ariad still needs: ${saved.missing_fields.join(', ')}.`)
        return
      }
      setStep('approve')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The project brief could not be prepared.')
    } finally { setBusy(false) }
  }

  async function approveBrief() {
    if (!token || !project || !approved) return
    setBusy(true); setError(null)
    try {
      setBrief(await confirmProjectBrief(project.project_id, token))
      setStep('ready')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The brief could not be approved.')
    } finally { setBusy(false) }
  }

  async function prepareDesign() {
    if (!token || !project || !brief) return
    setBusy(true); setError(null)
    try {
      const proposal = await getProjectDesignProposal(project.project_id, token)
      setDesignPlan(proposal.proposal); setPlanSource('codex')
    } catch (reason) {
      if (!(reason instanceof ApiError && reason.status === 404)) {
        setError(reason instanceof Error ? reason.message : 'The Design proposal could not be loaded.')
      }
      setDesignPlan(fallbackDesignPlan(prompt)); setPlanSource('local')
    } finally {
      setStep('design'); setBusy(false)
    }
  }

  function planLines(name: 'critical_features' | 'assembly_interfaces' | 'constraints' | 'unresolved_questions', value: string) {
    setDesignPlan((current) => ({ ...current, [name]: value.split('\n').map((item) => item.trim()).filter(Boolean) }))
  }

  async function persistDesign(event: FormEvent) {
    event.preventDefault()
    if (!token || !project) return
    setBusy(true); setError(null)
    try {
      setDesignPlan(await saveProjectDesignPlan(project.project_id, designPlan, token))
      setStep('planned')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The Design plan could not be saved.')
    } finally { setBusy(false) }
  }

  return (
    <div className="build-session">
      <header className="build-session-header">
        <div><p className="eyebrow">Guided Build Session</p><h1 data-route-heading tabIndex={-1}>Build from intent to evidence.</h1><p>Codex guides the build while Ariad keeps dimensions, parts, checks, and artifacts on one traceable thread.</p></div>
        <div className="build-session-status"><span>Evidence state</span><strong>{brief ? 'R0 · Brief confirmed' : 'Planning only'}</strong><small><i /> Local workspace · hardware off</small></div>
      </header>

      <ol className="build-stage-rail" aria-label="Build stages">
        {stageLabels.map((label, index) => <li className={index < activeIndex ? 'stage-done' : index === activeIndex ? 'stage-active' : ''} key={label}><span>{index < activeIndex ? '✓' : index + 1}</span>{label}</li>)}
      </ol>

      {step === 'describe' ? <section className="build-start-workspace">
        <div className="build-focus-card build-prompt-card">
          <div className="conversation-label"><span className="conversation-avatar">C</span><div><strong>Start with what you need</strong><small>Codex will turn intent into an editable fabrication brief.</small></div></div>
          <h2>What should Ariad help you make?</h2>
          <form onSubmit={understand}><textarea aria-label="What should Ariad help you make?" required rows={6} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Describe the object, how it should work, and anything it must fit. You can stay in plain language." /><div className="prompt-suggestion"><span>Try the demo idea</span><button type="button" onClick={() => setPrompt('Make a cute two-servo robot with long rotating side limbs that can recover when it falls. Design it as separate, serviceable parts with accessible fasteners.')}>Use robot example</button></div><button aria-label="Continue" className="primary-action" disabled={busy || !prompt.trim()}>{busy ? 'Understanding…' : 'Begin guided build →'}</button></form>
          <div className="build-promise"><span><b>01</b> Codex guides</span><span><b>02</b> Ariad verifies</span><span><b>03</b> You approve</span></div>
        </div>
        <aside className="build-preview-panel">
          <div className="preview-panel-heading"><div><p className="eyebrow">Your build companion</p><h2>Codex carries the technical thread.</h2></div><span className="live-indicator"><i /> Ready to guide</span></div>
          <div className="codex-guide-card"><div className="guide-avatar">C</div><div><strong>What happens next</strong><p>Codex will turn your description into a short build brief, surface only blocking questions, and prepare a staged design plan for your approval.</p></div></div>
          <ol className="guide-steps"><li><b>01</b><span><strong>Understand</strong><small>Extract the outcome and constraints</small></span></li><li><b>02</b><span><strong>Clarify</strong><small>Ask only what cannot be safely assumed</small></span></li><li><b>03</b><span><strong>Prepare</strong><small>Plan parts and evidence before geometry</small></span></li></ol>
          <div className="guide-boundary"><span>Human input</span><strong>You approve the brief.</strong><small>Codex handles the planning detail.</small></div>
        </aside>
      </section> : null}

      {step === 'review' ? <section className="build-review-grid">
        <div className="build-focus-card">
          <p className="eyebrow">Suggested build brief</p><h2>Review the choices that shape the result</h2>
          <p className="gentle-note">These are editable defaults, not hidden decisions. Saving creates a project and draft only—no CAD or evidence.</p>
          <details className="advanced-details"><summary>Show technical details</summary><div className="build-fields">
            <label>Project name<input value={draft.name ?? ''} onChange={(e) => text('name', e.target.value)} /></label>
            <label>Purpose<input value={draft.purpose ?? ''} onChange={(e) => text('purpose', e.target.value)} /></label>
            <label>Product type<input value={draft.part_type ?? ''} onChange={(e) => text('part_type', e.target.value)} /></label>
            <div className="dimension-row"><label>Length<input type="number" min="1" value={draft.size_x_mm ?? ''} onChange={(e) => number('size_x_mm', e.target.value)} /></label><label>Width<input type="number" min="1" value={draft.size_y_mm ?? ''} onChange={(e) => number('size_y_mm', e.target.value)} /></label><label>Height<input type="number" min="1" value={draft.size_z_mm ?? ''} onChange={(e) => number('size_z_mm', e.target.value)} /></label></div>
            <label>Material<select value={draft.material ?? ''} onChange={(e) => text('material', e.target.value)}><option>PETG</option><option>PLA</option><option>TPU</option></select></label>
            <label>Fit allowance (mm)<input type="number" min="0.05" step="0.05" value={draft.tolerance_mm ?? ''} onChange={(e) => number('tolerance_mm', e.target.value)} /></label>
            <label>Supports<select value={draft.support_policy ?? 'avoid'} onChange={(e) => text('support_policy', e.target.value)}><option value="avoid">Avoid where practical</option><option value="allowed">Allowed</option><option value="required">Expected</option></select></label>
          </div></details>
          <button className="primary-action" disabled={busy || !token} onClick={prepareBrief}>{busy ? 'Preparing…' : 'Save project and prepare brief'}</button>
        </div>
        <aside className="build-context-card build-codex-summary">
          <div className="summary-agent"><span className="guide-avatar">C</span><div><p className="eyebrow">Codex understood</p><h3>{reviewSummary}</h3></div></div><p>{reviewReason}</p>
          <div className="assumption-list"><strong>Working assumptions</strong><span>FDM process</span><span>General-use safety class</span><span>Printer selected later</span></div>
          {reviewQuestion ? <div className="blocking-question"><strong>Decision to revisit</strong><p>{reviewQuestion}</p></div> : null}
        </aside>
      </section> : null}

      {step === 'approve' ? <section className="build-focus-card approval-focus">
        <p className="eyebrow">Human checkpoint</p><h2>Approve this brief for Design</h2><p>The project and complete draft are saved. Approval creates R0 evidence, but does not generate CAD, slice, print, or contact hardware.</p>
        <dl className="brief-summary"><div><dt>Project</dt><dd>{draft.name}</dd></div><div><dt>Envelope</dt><dd>{draft.size_x_mm} × {draft.size_y_mm} × {draft.size_z_mm} mm</dd></div><div><dt>Material</dt><dd>{draft.material}</dd></div><div><dt>Fit allowance</dt><dd>{draft.tolerance_mm} mm</dd></div></dl>
        <label className="approval-check"><input type="checkbox" checked={approved} onChange={(event) => setApproved(event.target.checked)} /> I reviewed these assumptions and approve this Brief for Design.</label>
        <button className="primary-action" disabled={!approved || busy} onClick={approveBrief}>{busy ? 'Recording approval…' : 'Approve brief'}</button>
      </section> : null}

      {step === 'ready' && brief && project ? <section className="build-complete-card">
        <div className="completion-mark">✓</div><p className="eyebrow">Thread secured</p><h2>Your idea is ready for the Design stage</h2><p>R0 records what you approved. CAD is still absent, so Ariad makes no geometry or printability claim yet.</p>
        <div className="next-actions"><button className="primary-action" disabled={busy} onClick={prepareDesign}>{busy ? 'Preparing Design…' : 'Prepare Design plan'}</button><Link className="secondary-action" to={`/jobs/${encodeURIComponent(brief.job_id)}/revisions/${encodeURIComponent(brief.revision_id)}`}>Inspect R0 evidence</Link></div>
      </section> : null}

      {step === 'design' ? <section className="design-session-card">
        <div className="design-session-heading"><div><p className="eyebrow">Design plan · not saved</p><h2>How should Ariad build it?</h2><p>{planSource === 'codex' ? 'Codex proposed this plan from the confirmed Brief.' : 'Ariad prepared a transparent local fallback because no Codex proposal was available.'}</p></div><span className={`plan-source plan-source-${planSource}`}>{planSource === 'codex' ? 'Codex proposal' : 'Local fallback'}</span></div>
        <form onSubmit={persistDesign}>
          <label>Design lane<select value={designPlan.lane} onChange={(event) => setDesignPlan((current) => ({ ...current, lane: event.target.value as ProjectDesignPlanRequest['lane'] }))}><option value="functional_parametric">Functional parametric CAD</option><option value="organic_mesh">Organic mesh</option><option value="hybrid">Hybrid CAD and mesh</option><option value="undecided">Undecided</option></select></label>
          <label>Geometry strategy<textarea required rows={4} value={designPlan.geometry_strategy} onChange={(event) => setDesignPlan((current) => ({ ...current, geometry_strategy: event.target.value }))} /></label>
          <div className="design-plan-summary"><p className="eyebrow">Codex prepared</p><h3>{designPlan.geometry_strategy}</h3><div className="plan-chip-row">{designPlan.critical_features.slice(0, 3).map((item) => <span key={item}>{item}</span>)}</div></div>
          <details className="advanced-details design-advanced"><summary>Inspect the full Design plan</summary><div className="design-session-grid"><label>Critical features<textarea rows={6} value={designPlan.critical_features.join('\n')} onChange={(event) => planLines('critical_features', event.target.value)} /></label><label>Assembly interfaces<textarea rows={6} value={designPlan.assembly_interfaces.join('\n')} onChange={(event) => planLines('assembly_interfaces', event.target.value)} /></label><label>Constraints<textarea rows={6} value={designPlan.constraints.join('\n')} onChange={(event) => planLines('constraints', event.target.value)} /></label><label>Open decisions<textarea rows={6} value={designPlan.unresolved_questions.join('\n')} onChange={(event) => planLines('unresolved_questions', event.target.value)} /></label></div></details>
          <div className="design-save-row"><p>Saving records planning only. It does not run generated code or create R1.</p><button className="primary-action" disabled={busy}>{busy ? 'Saving plan…' : 'Save Design plan'}</button></div>
        </form>
      </section> : null}

      {step === 'planned' && project ? <section className="build-complete-card">
        <div className="completion-mark">✓</div><p className="eyebrow">Design thread prepared</p><h2>Codex has prepared the next build step.</h2><p>Ariad has a structured Design strategy, features, interfaces, constraints, and open decisions. No CAD worker ran, so R1, geometry verification, simulation, and printability remain unavailable.</p><AssemblyBlueprint compact />
        <div className="next-actions"><Link className="primary-action" to={`/projects/${encodeURIComponent(project.project_id)}`}>Open project details</Link><Link className="secondary-action" to={`/chat?project=${encodeURIComponent(project.project_id)}`}>Discuss open decisions with Codex</Link></div>
      </section> : null}

      {error ? <div className="build-error" role="alert">{error}</div> : null}
    </div>
  )
}
