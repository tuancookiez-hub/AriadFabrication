import { type FormEvent, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { AssemblyBlueprint } from './AssemblyBlueprint'
import { RobotCadWorkspace } from './RobotCadWorkspace'
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

type SessionStep = 'describe' | 'review' | 'blueprint' | 'cad' | 'verify' | 'slice' | 'package'

const BUILD_SESSION_KEY = 'ariad.active-build.v2'

type StoredBuildSession = {
  step: SessionStep
  prompt: string
  intake: IntakeResponse | null
  draft: ProjectDraftRequest
  project: ProjectIntent | null
  brief: ProjectBrief | null
  designPlan: ProjectDesignPlanRequest
  planSource: 'codex' | 'local' | null
}

function restoreBuildSession(): StoredBuildSession | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(BUILD_SESSION_KEY) ?? 'null') as Partial<StoredBuildSession> | null
    if (!value || !['describe', 'review', 'blueprint', 'cad', 'verify', 'slice', 'package'].includes(value.step ?? '') || typeof value.prompt !== 'string' || !value.draft || !value.designPlan) return null
    return value as StoredBuildSession
  } catch {
    return null
  }
}

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
      ? ['Confirm exact servo and horn', 'Confirm camera module', 'Confirm compute board and battery', 'Calibrate interlock clearances on the eventual printer']
      : ['Confirm the exact real-world object that defines the critical fit'],
  }
}

const stageLabels = ['Idea', 'Confirm', 'Blueprint', 'CAD', 'Verify', 'Slice', 'Package']
const stageIndex: Record<SessionStep, number> = {
  describe: 0,
  review: 1,
  blueprint: 2,
  cad: 3,
  verify: 4,
  slice: 5,
  package: 6,
}

export function BuildSessionPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [restored] = useState(() => searchParams.get('new') === '1' ? null : restoreBuildSession())
  const [step, setStep] = useState<SessionStep>(restored?.step ?? 'describe')
  const [prompt, setPrompt] = useState(restored?.prompt ?? '')
  const [intake, setIntake] = useState<IntakeResponse | null>(restored?.intake ?? null)
  const [draft, setDraft] = useState<ProjectDraftRequest>(restored?.draft ?? suggestedDraft(''))
  const [token, setToken] = useState<string | null>(null)
  const [project, setProject] = useState<ProjectIntent | null>(restored?.project ?? null)
  const [brief, setBrief] = useState<ProjectBrief | null>(restored?.brief ?? null)
  const [designPlan, setDesignPlan] = useState<ProjectDesignPlanRequest>(restored?.designPlan ?? fallbackDesignPlan(''))
  const [planSource, setPlanSource] = useState<'codex' | 'local' | null>(restored?.planSource ?? null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getBrowserSession(controller.signal).then((session) => setToken(session.session_token)).catch(() => setToken(null))
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (searchParams.get('new') !== '1') return
    sessionStorage.removeItem(BUILD_SESSION_KEY)
    setSearchParams({}, { replace: true })
  }, [searchParams, setSearchParams])

  useEffect(() => {
    const value: StoredBuildSession = { step, prompt, intake, draft, project, brief, designPlan, planSource }
    sessionStorage.setItem(BUILD_SESSION_KEY, JSON.stringify(value))
  }, [brief, designPlan, draft, intake, planSource, project, prompt, step])

  const activeIndex = useMemo(() => stageIndex[step], [step])
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

  async function approveRecommendedBrief() {
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
      const confirmed = await confirmProjectBrief(created.project_id, token)
      setBrief(confirmed)
      let proposedPlan: ProjectDesignPlanRequest
      try {
        const proposal = await getProjectDesignProposal(created.project_id, token)
        proposedPlan = proposal.proposal
        setPlanSource('codex')
      } catch (reason) {
        if (!(reason instanceof ApiError && reason.status === 404)) setError(reason instanceof Error ? reason.message : 'The Design proposal could not be loaded.')
        proposedPlan = fallbackDesignPlan(prompt)
        setPlanSource('local')
      }
      const savedPlan = await saveProjectDesignPlan(created.project_id, proposedPlan, token)
      setDesignPlan(savedPlan)
      setStep(prompt.toLowerCase().includes('robot') ? 'blueprint' : 'cad')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The project brief could not be prepared.')
    } finally { setBusy(false) }
  }

  function goBack() {
    setError(null)
    if (step === 'package') setStep('slice')
    else if (step === 'slice') setStep('verify')
    else if (step === 'verify') setStep('cad')
    else if (step === 'cad') setStep(prompt.toLowerCase().includes('robot') ? 'blueprint' : 'review')
    else if (step === 'blueprint') setStep('review')
    else if (step === 'review') setStep('describe')
  }

  const backLabel = step === 'package' ? 'Back to slice' : step === 'slice' ? 'Back to verification' : step === 'verify' ? 'Back to CAD' : step === 'cad' ? 'Back to blueprint' : step === 'blueprint' ? 'Back to requirements' : step === 'review' ? 'Back to idea' : null

  return (
    <div className="build-session">
      <header className={`build-session-header${step === 'describe' ? ' build-session-header-intake' : ''}`}>
        <div><p className="eyebrow">Make something</p><h1 data-route-heading tabIndex={-1}>{['cad', 'verify', 'slice', 'package'].includes(step) ? 'Your model stays at the center.' : step === 'blueprint' ? 'Check the design before CAD.' : 'Tell Codex what you need.'}</h1><p>{['cad', 'verify', 'slice', 'package'].includes(step) ? 'Inspect it, ask for a change, or continue. Ariad keeps the technical records in the background.' : step === 'blueprint' ? 'Confirm the shape, parts, and assembly idea. Dimensions still come from the CAD that follows.' : 'Ariad guides the design and shows technical detail only when you ask for it.'}</p></div>
        <div className="build-session-status"><span>Current step</span><strong>{step === 'package' ? 'Reviewing the package' : step === 'slice' ? 'Reviewing the real slice' : step === 'verify' ? 'Checking print preparation' : step === 'cad' ? 'Inspecting CAD' : step === 'blueprint' ? 'Approving visual intent' : step === 'review' ? 'Confirm the brief' : 'Describe your idea'}</strong><small><i /> Codex is guiding</small></div>
      </header>

      <ol className="build-stage-rail" aria-label="Build stages">
        {stageLabels.map((label, index) => <li className={index < activeIndex ? 'stage-done' : index === activeIndex ? 'stage-active' : ''} key={label}><span>{index < activeIndex ? '✓' : index + 1}</span>{label}</li>)}
      </ol>
      {backLabel ? <div className="build-navigation"><button type="button" onClick={goBack}>← {backLabel}</button><span>Your work is preserved when you move between steps.</span></div> : null}

      {step === 'describe' ? <section className="build-start-workspace">
        <div className="build-focus-card build-prompt-card">
          <div className="conversation-label"><span className="conversation-avatar">C</span><div><strong>Start with what you need</strong><small>Codex will turn intent into an editable fabrication brief.</small></div></div>
          <h2>What should Ariad help you make?</h2>
      <form onSubmit={understand}><textarea aria-label="What should Ariad help you make?" required rows={6} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Describe the object, how it should work, and anything it must fit. You can stay in plain language." /><div className="prompt-suggestion"><span>Try the demo idea</span><button type="button" onClick={() => setPrompt('Make a cute two-servo robot with long rotating side limbs that can recover when it falls. Design it as separate, serviceable parts that slide or snap together without glue or screws between printed parts.')}>Use robot example</button></div><button aria-label="Continue" className="primary-action" disabled={busy || !prompt.trim()}>{busy ? 'Understanding…' : 'Begin guided build →'}</button></form>
        </div>
        <aside className="build-preview-panel">
          <div className="preview-panel-heading"><div><p className="eyebrow">Your build companion</p><h2>Codex will guide this build.</h2></div><span className="live-indicator"><i /> Ready</span></div>
          <ol className="guide-steps guide-steps-simple"><li><b>01</b><span><strong>Understand your idea</strong></span></li><li><b>02</b><span><strong>Ask only what matters</strong></span></li><li><b>03</b><span><strong>Prepare the plan</strong></span></li></ol>
          <div className="guide-boundary"><strong>You approve. Codex handles the detail.</strong></div>
        </aside>
      </section> : null}

      {step === 'review' ? <section className="build-review-grid">
        <div className="build-focus-card">
          <p className="eyebrow">Suggested build brief</p><h2>Review the choices that shape the result</h2>
          <p className="gentle-note">Codex prepared this recommendation. Approve it once; Ariad will prepare the CAD plan and continue the build.</p>
          <details className="advanced-details"><summary>Optional technical details</summary><div className="build-fields">
            <label>Project name<input value={draft.name ?? ''} onChange={(e) => text('name', e.target.value)} /></label>
            <label>Purpose<input value={draft.purpose ?? ''} onChange={(e) => text('purpose', e.target.value)} /></label>
            <label>Product type<input value={draft.part_type ?? ''} onChange={(e) => text('part_type', e.target.value)} /></label>
            <div className="dimension-row"><label>Length<input type="number" min="1" value={draft.size_x_mm ?? ''} onChange={(e) => number('size_x_mm', e.target.value)} /></label><label>Width<input type="number" min="1" value={draft.size_y_mm ?? ''} onChange={(e) => number('size_y_mm', e.target.value)} /></label><label>Height<input type="number" min="1" value={draft.size_z_mm ?? ''} onChange={(e) => number('size_z_mm', e.target.value)} /></label></div>
            <label>Material<select value={draft.material ?? ''} onChange={(e) => text('material', e.target.value)}><option>PETG</option><option>PLA</option><option>TPU</option></select></label>
            <label>Fit allowance (mm)<input type="number" min="0.05" step="0.05" value={draft.tolerance_mm ?? ''} onChange={(e) => number('tolerance_mm', e.target.value)} /></label>
            <label>Supports<select value={draft.support_policy ?? 'avoid'} onChange={(e) => text('support_policy', e.target.value)}><option value="avoid">Avoid where practical</option><option value="allowed">Allowed</option><option value="required">Expected</option></select></label>
          </div></details>
          <button className="primary-action" disabled={busy || !token} onClick={approveRecommendedBrief}>{busy ? 'Preparing CAD plan…' : 'Approve and continue'}</button>
        </div>
        <aside className="build-context-card build-codex-summary">
          <div className="summary-agent"><span className="guide-avatar">C</span><div><p className="eyebrow">Codex understood</p><h3>{reviewSummary}</h3></div></div><p>{reviewReason}</p>
          <div className="assumption-list"><strong>Working assumptions</strong><span>FDM process</span><span>General-use safety class</span><span>Printer selected later</span></div>
          {reviewQuestion ? <div className="blocking-question"><strong>Decision to revisit</strong><p>{reviewQuestion}</p></div> : null}
        </aside>
      </section> : null}

      {step === 'blueprint' && project && prompt.toLowerCase().includes('robot') ? <section className="blueprint-approval-stage">
        <div className="blueprint-approval-heading"><div><p className="eyebrow">Generated visual blueprint</p><h2>Does this match what you meant?</h2><p>Check the silhouette, two side limbs, service access, and tool-less part breakdown. This image guides the CAD; it does not provide dimensions or prove fit.</p></div><span>Concept only</span></div>
        <AssemblyBlueprint compact />
        <div className="blueprint-approval-actions"><Link className="secondary-action" to={`/chat?project=${encodeURIComponent(project.project_id)}`}>Ask Codex for a visual change</Link><button className="primary-action" type="button" onClick={() => setStep('cad')}>Approve blueprint and inspect CAD</button></div>
      </section> : null}

      {(['blueprint', 'cad', 'verify', 'slice', 'package'] as SessionStep[]).includes(step) && project ? <details className="build-work-log"><summary>What Codex prepared</summary><div><strong>{planSource === 'codex' ? 'Codex-authored plan' : 'Local deterministic plan'}</strong><p>{designPlan.geometry_strategy}</p><span>{designPlan.critical_features.length} features · {designPlan.assembly_interfaces.length} interfaces · {designPlan.unresolved_questions.length} open decisions</span></div></details> : null}

      {(['cad', 'verify', 'slice', 'package'] as SessionStep[]).includes(step) && project && !prompt.toLowerCase().includes('robot') ? <section className="build-complete-card">
        <div className="completion-mark">✓</div><p className="eyebrow">Design plan saved</p><h2>This idea needs a qualified CAD family.</h2><p>Ariad will not invent printable geometry for an unsupported family. The approved robot example is currently the first connected CAD path.</p>
        <div className="next-actions"><Link className="primary-action" to={`/projects/${encodeURIComponent(project.project_id)}`}>Review project thread</Link><Link className="secondary-action" to={`/chat?project=${encodeURIComponent(project.project_id)}`}>Discuss open decisions with Codex</Link></div>
      </section> : null}

      {(['cad', 'verify', 'slice', 'package'] as SessionStep[]).includes(step) && project && prompt.toLowerCase().includes('robot') ? <RobotCadWorkspace mode={step as 'cad' | 'verify' | 'slice' | 'package'} projectId={project.project_id} onContinue={() => setStep(step === 'cad' ? 'verify' : step === 'verify' ? 'slice' : 'package')} /> : null}

      {error ? <div className="build-error" role="alert">{error}</div> : null}
    </div>
  )
}
