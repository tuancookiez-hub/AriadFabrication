import { type FormEvent, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { AssemblyBlueprint } from './AssemblyBlueprint'
import { BuildCodexPanel } from './BuildCodexPanel'
import { LiveBracketWorkspace } from './LiveBracketWorkspace'
import { LiveDeclarativeWorkspace } from './LiveDeclarativeWorkspace'
import { RobotCadWorkspace } from './RobotCadWorkspace'
import {
  ApiError,
  captureIdea,
  confirmProjectBrief,
  createProjectIntent,
  getBrowserSession,
  getCodexEvents,
  getLocalCodexStatus,
  getProjectCadProposal,
  getProjectDesignProposal,
  generateLiveLBracket,
  generateProjectCad,
  saveProjectDesignPlan,
  saveProjectDraft,
  startCodexTurn,
} from './api'
import type { DeclarativeCad, IntakeResponse, LiveLBracket, LiveLBracketRequest, ProjectBrief, ProjectDesignPlanRequest, ProjectDraftRequest, ProjectIntent } from './types'

type SessionStep = 'describe' | 'review' | 'components' | 'blueprint' | 'cad' | 'verify' | 'slice' | 'package'

type BuildPath = 'universal' | 'live_bracket' | 'robot_reference'

const BUILD_SESSION_KEY = 'ariad.active-build.v3'

type StoredBuildSession = {
  step: SessionStep
  prompt: string
  intake: IntakeResponse | null
  draft: ProjectDraftRequest
  project: ProjectIntent | null
  brief: ProjectBrief | null
  designPlan: ProjectDesignPlanRequest
  planSource: 'codex' | 'local' | null
  buildPath: BuildPath
  liveCad: LiveLBracket | null
  declarativeCad: DeclarativeCad | null
}

function restoreBuildSession(): StoredBuildSession | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(BUILD_SESSION_KEY) ?? 'null') as Partial<StoredBuildSession> | null
    if (!value || !['describe', 'review', 'components', 'blueprint', 'cad', 'verify', 'slice', 'package'].includes(value.step ?? '') || typeof value.prompt !== 'string' || !value.draft || !value.designPlan) return null
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
  const bracket = /\b(?:l[ -]?bracket|bracket)\b/i.test(prompt)
  const dimensions = prompt.match(/(\d+(?:\.\d+)?)\s*(?:mm)?\s*[x×]\s*(\d+(?:\.\d+)?)\s*(?:mm)?\s*[x×]\s*(\d+(?:\.\d+)?)\s*mm\b/i)
  return {
    name: suggestedTitle(prompt),
    purpose: prompt.trim(),
    part_type: suggestedPartType(prompt),
    size_x_mm: dimensions ? Number(dimensions[1]) : robot ? 120 : bracket ? 60 : 100,
    size_y_mm: dimensions ? Number(dimensions[2]) : robot ? 58 : bracket ? 40 : 100,
    size_z_mm: dimensions ? Number(dimensions[3]) : robot ? 167 : bracket ? 45 : 100,
    material: 'PETG',
    tolerance_mm: 0.3,
    support_policy: 'avoid',
    manufacturing_process: 'FDM',
    safety_class: 'general',
  }
}

function liveBracketRequest(projectId: string, draft: ProjectDraftRequest): LiveLBracketRequest {
  const width = Number(draft.size_x_mm ?? 60)
  const depth = Number(draft.size_y_mm ?? 40)
  const height = Number(draft.size_z_mm ?? 45)
  const thickness = Math.max(3, Math.min(6, Math.round(Math.min(depth, height) * 0.1 * 10) / 10))
  const holeDiameter = 4.2
  const edgeMargin = Math.max(4, Math.min(8, Math.round(width * 0.1 * 10) / 10))
  const maximumSpacing = width - 2 * (holeDiameter / 2 + edgeMargin)
  return {
    project_id: projectId,
    width_mm: width,
    base_depth_mm: depth,
    upright_height_mm: height,
    thickness_mm: thickness,
    hole_diameter_mm: holeDiameter,
    hole_spacing_mm: Math.round(Math.min(width * 0.55, maximumSpacing) * 10) / 10,
    edge_margin_mm: edgeMargin,
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
      ? ['Pi Zero 2 W four-hole carrier', 'Two structurally captured SCS0009 servos', 'Serviceable body shell', 'Unobstructed camera-board frame']
      : ['Approved overall envelope', 'Critical fit interface', 'Minimum wall thickness'],
    assembly_interfaces: robot
      ? ['Shell to electronics tray', 'Left and right servo-to-limb joints', 'Camera to bezel', 'Service panel access']
      : ['Primary mating interface'],
    constraints: ['FDM manufacturing', 'Avoid supports where practical', 'Preserve user-approved dimensions and evidence boundaries'],
    unresolved_questions: robot
      ? ['Measure the supplied servo horns', 'Select the exact OV5647 camera and IMU boards', 'Confirm the regulated 5 V tether', 'Calibrate interlock clearances on the eventual printer']
      : ['Confirm the exact real-world object that defines the critical fit'],
  }
}

const stageLabels = ['Idea', 'Confirm', 'Components', 'Blueprint', 'CAD', 'Verify', 'Slice', 'Package']
const stageIndex: Record<SessionStep, number> = {
  describe: 0,
  review: 1,
  components: 2,
  blueprint: 3,
  cad: 4,
  verify: 5,
  slice: 6,
  package: 7,
}
const bracketStageLabels = ['Idea', 'Confirm', 'CAD', 'Verify', 'Slice', 'Package']
const bracketStageIndex: Partial<Record<SessionStep, number>> = { describe: 0, review: 1, cad: 2, verify: 3, slice: 4, package: 5 }
const wait = (milliseconds: number) => new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds))

export function BuildSessionPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [restored] = useState(() => searchParams.get('new') === '1' ? null : restoreBuildSession())
  const [step, setStep] = useState<SessionStep>(restored?.step ?? 'describe')
  const [prompt, setPrompt] = useState(restored?.prompt ?? '')
  const [intake, setIntake] = useState<IntakeResponse | null>(restored?.intake ?? null)
  const [draft, setDraft] = useState<ProjectDraftRequest>(restored?.draft ?? suggestedDraft(''))
  const [token, setToken] = useState<string | null>(null)
  const [codexAvailable, setCodexAvailable] = useState(false)
  const [project, setProject] = useState<ProjectIntent | null>(restored?.project ?? null)
  const [brief, setBrief] = useState<ProjectBrief | null>(restored?.brief ?? null)
  const [designPlan, setDesignPlan] = useState<ProjectDesignPlanRequest>(restored?.designPlan ?? fallbackDesignPlan(''))
  const [planSource, setPlanSource] = useState<'codex' | 'local' | null>(restored?.planSource ?? null)
  const [buildPath, setBuildPath] = useState<BuildPath>(restored?.buildPath ?? 'universal')
  const [liveCad, setLiveCad] = useState<LiveLBracket | null>(restored?.liveCad ?? null)
  const [declarativeCad, setDeclarativeCad] = useState<DeclarativeCad | null>(restored?.declarativeCad ?? null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [generationStatus, setGenerationStatus] = useState<string | null>(null)
  const [codexContext, setCodexContext] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getBrowserSession(controller.signal).then((session) => setToken(session.session_token)).catch(() => setToken(null))
    getLocalCodexStatus(controller.signal).then((status) => setCodexAvailable(status.conversation_available)).catch(() => setCodexAvailable(false))
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (searchParams.get('new') !== '1') return
    sessionStorage.removeItem(BUILD_SESSION_KEY)
    setSearchParams({}, { replace: true })
  }, [searchParams, setSearchParams])

  useEffect(() => {
    const value: StoredBuildSession = { step, prompt, intake, draft, project, brief, designPlan, planSource, buildPath, liveCad, declarativeCad }
    sessionStorage.setItem(BUILD_SESSION_KEY, JSON.stringify(value))
  }, [brief, buildPath, declarativeCad, designPlan, draft, intake, liveCad, planSource, project, prompt, step])

  const robotPath = buildPath === 'robot_reference'
  const directCadPath = buildPath !== 'robot_reference'
  const displayedStageLabels = directCadPath ? bracketStageLabels : stageLabels
  const activeIndex = useMemo(() => directCadPath ? (bracketStageIndex[step] ?? 0) : stageIndex[step], [directCadPath, step])
  const localFallback = intake?.provider.configured === false
  const reviewSummary = localFallback ? suggestedPartType(prompt) : intake?.route.summary
  const reviewReason = localFallback
    ? 'Ariad prepared editable local defaults. No model classified this request, so exact product decisions stay visible.'
    : intake?.route.reason
  const reviewQuestion = localFallback
    ? (robotPath
        ? 'Use a Pi Zero 2 W and SCS0009 servos now; select the exact camera, IMU, and power cable before physical release.'
        : 'Which exact real-world object or component should define the critical fit?')
    : intake?.route.questions[0]

  async function understand(event: FormEvent) {
    event.preventDefault()
    setBusy(true); setError(null)
    try {
      const result = await captureIdea(prompt)
      setLiveCad(null); setDeclarativeCad(null); setIntake(result); setDraft(suggestedDraft(prompt)); setStep('review')
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

  async function generateWithCodex(projectId: string, revisionInstruction?: string): Promise<DeclarativeCad> {
    if (!token || !codexAvailable) {
      throw new Error('General generation needs a locally authenticated Codex CLI. Connect Codex or use the live bracket/reference paths.')
    }
    let correction = revisionInstruction
      ? `Revise the current declarative CAD proposal with this instruction: ${revisionInstruction}`
      : ''
    for (let attempt = 0; attempt < 2; attempt += 1) {
      setGenerationStatus(attempt === 0 ? 'Codex is composing bounded geometry…' : 'Codex is correcting a geometry failure…')
      const request = [
        `Create a declarative CAD proposal for confirmed Ariad project ${projectId}.`,
        `User request: ${prompt.slice(0, 12_000)}`,
        `Approved envelope: ${draft.size_x_mm ?? 'unknown'} × ${draft.size_y_mm ?? 'unknown'} × ${draft.size_z_mm ?? 'unknown'} mm.`,
        `Material/process context: ${draft.material ?? 'unspecified'} / ${draft.manufacturing_process ?? 'unspecified'}.`,
        correction,
        'Call ariad.propose_cad_document exactly once with a practical multi-part CSG approximation. Use only the registered primitives and make every boolean operand intersect. Do not merely explain the design.',
      ].filter(Boolean).join('\n')
      const turn = await startCodexTurn(request, token)
      let after = 0
      let terminal: string | null = null
      let proposalCompleted = false
      let proposalFailed = false
      const deadline = Date.now() + 125_000
      while (!terminal && Date.now() < deadline) {
        await wait(500)
        const events = await getCodexEvents(after, token)
        after = events.next_sequence
        for (const event of events.events) {
          if (event.turn_id !== turn.turn_id) continue
          if (event.event_type === 'tool_started' && event.tool_name === 'ariad.propose_cad_document') setGenerationStatus('Codex proposed a CSG document. Ariad is checking it…')
          if (event.event_type === 'tool_completed' && event.tool_name === 'ariad.propose_cad_document') {
            proposalCompleted = true
            setGenerationStatus('Proposal accepted. Ariad is building exact geometry…')
          }
          if (event.event_type === 'tool_failed' && event.tool_name === 'ariad.propose_cad_document') proposalFailed = true
          if (['turn_completed', 'turn_failed', 'turn_cancelled'].includes(event.event_type)) terminal = event.event_type
        }
      }
      if (terminal !== 'turn_completed') throw new Error(terminal ? `Codex generation ended with ${terminal.replaceAll('_', ' ')}.` : 'Codex generation exceeded the time boundary.')
      if (!proposalCompleted) {
        throw new Error(proposalFailed
          ? 'Codex submitted a CAD proposal, but Ariad rejected its contract before geometry generation.'
          : 'Codex completed without submitting a new CAD proposal. Try the request again with clearer dimensions and hard-surface features.')
      }
      await getProjectCadProposal(projectId, token)
      try {
        return await generateProjectCad(projectId, token)
      } catch (reason) {
        if (!(reason instanceof ApiError && reason.status === 422 && attempt === 0)) throw reason
        correction = `Ariad rejected the previous geometry: ${reason.message}. Replace it with a simpler connected, single-solid-per-part proposal.`
      }
    }
    throw new Error('Codex could not produce kernel-valid bounded geometry after one correction.')
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
      if (buildPath === 'live_bracket') {
        setLiveCad(await generateLiveLBracket(liveBracketRequest(created.project_id, draft), token))
        setStep('cad')
      } else if (buildPath === 'robot_reference') {
        setStep('components')
      } else {
        setDeclarativeCad(await generateWithCodex(created.project_id))
        setStep('cad')
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The project brief could not be prepared.')
    } finally { setBusy(false); setGenerationStatus(null) }
  }

  async function reviseDeclarativeCad(instruction: string) {
    if (!project) return
    setBusy(true); setError(null)
    try {
      setDeclarativeCad(await generateWithCodex(project.project_id, instruction))
      setStep('cad')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The model revision failed.')
    } finally { setBusy(false); setGenerationStatus(null) }
  }

  function goBack() {
    setError(null)
    if (step === 'package') setStep('slice')
    else if (step === 'slice') setStep('verify')
    else if (step === 'verify') setStep('cad')
    else if (step === 'cad') setStep(robotPath ? 'blueprint' : 'review')
    else if (step === 'blueprint') setStep('components')
    else if (step === 'components') setStep('review')
    else if (step === 'review') setStep('describe')
  }

  const backLabel = step === 'package' ? 'Back to slice' : step === 'slice' ? 'Back to verification' : step === 'verify' ? 'Back to CAD' : step === 'cad' ? (robotPath ? 'Back to blueprint' : 'Back to requirements') : step === 'blueprint' ? 'Back to components' : step === 'components' ? 'Back to requirements' : step === 'review' ? 'Back to idea' : null

  return (
    <div className="build-session">
      <header className={`build-session-header${step === 'describe' ? ' build-session-header-intake' : ''}`}>
        <div><p className="eyebrow">Make something</p><h1 data-route-heading tabIndex={-1}>{['cad', 'verify', 'slice', 'package'].includes(step) ? 'Your model stays at the center.' : step === 'components' ? 'Choose what the body must fit.' : step === 'blueprint' ? 'Check the design before CAD.' : 'Tell Codex what you need.'}</h1><p>{['cad', 'verify', 'slice', 'package'].includes(step) ? 'Inspect it, ask for a change, or continue. Ariad keeps the technical records in the background.' : step === 'components' ? 'Codex selected a safe first hardware layout. Confirm it before Ariad shapes the shell.' : step === 'blueprint' ? 'Confirm the component-aware shape and assembly idea before CAD.' : 'Ariad guides the design and shows technical detail only when you ask for it.'}</p></div>
        <div className="build-session-status"><span>Current step</span><strong>{step === 'package' ? 'Reviewing the package' : step === 'slice' ? 'Reviewing the real slice' : step === 'verify' ? 'Checking print preparation' : step === 'cad' ? 'Inspecting CAD' : step === 'blueprint' ? 'Approving the blueprint' : step === 'components' ? 'Confirming hardware' : step === 'review' ? 'Confirm the brief' : 'Describe your idea'}</strong><small><i /> Guided workflow active</small></div>
      </header>

      <ol className="build-stage-rail" aria-label="Build stages" style={{ gridTemplateColumns: `repeat(${displayedStageLabels.length}, 1fr)` }}>
        {displayedStageLabels.map((label, index) => <li className={index < activeIndex ? 'stage-done' : index === activeIndex ? 'stage-active' : ''} key={label}><span>{index < activeIndex ? '✓' : index + 1}</span>{label}</li>)}
      </ol>
      {backLabel ? <div className="build-navigation"><button type="button" onClick={goBack}>← {backLabel}</button><span>Your work is preserved when you move between steps.</span></div> : null}

      {step === 'describe' ? <section className="build-start-workspace">
        <div className="build-focus-card build-prompt-card">
          <div className="conversation-label"><span className="conversation-avatar">C</span><div><strong>Start with what you need</strong><small>Codex will turn intent into an editable fabrication brief.</small></div></div>
          <h2>What should Ariad help you make?</h2>
      <form onSubmit={understand}>
        <textarea aria-label="What should Ariad help you make?" required rows={6} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Describe any hard-surface object, how it should work, and anything it must fit. Codex will attempt a new bounded CSG design." />
        <div className="prompt-suggestion"><span>Try a new prompt-to-CAD build</span><button type="button" onClick={() => { setPrompt('Make an 80 x 60 x 80 mm desktop phone stand with a stable base, angled back support, front retaining lip, and a cable opening.'); setBuildPath('universal') }}>Use phone stand example</button></div>
        <div className="prompt-suggestion"><span>Use the deterministic family test</span><button type="button" onClick={() => { setPrompt('Make a 60 x 40 x 45 mm L-bracket in PETG for mounting a small controller.'); setBuildPath('live_bracket') }}>Use live bracket example</button></div>
        <div className="prompt-suggestion"><span>Explore the prepared full-evidence reference</span><button type="button" onClick={() => { setPrompt('Make a cute two-servo robot around a Raspberry Pi Zero 2 W, two SCS0009 servos, a camera, and an IMU. Give it exactly two long rotating side limbs and no fixed feet so it can explore recovery after a fall. Use separate serviceable printed parts and external regulated power for the first revision.'); setBuildPath('robot_reference') }}>Use robot reference</button></div>
        <div className="supported-path-note"><strong>General generation is now an attempt, not a fixture swap</strong><span>Codex proposes a new closed CSG document for your prompt; Ariad executes and checks it. Organic shapes, semantic fit, and printability may still need revision.</span></div>
        <button aria-label="Continue" className="primary-action" disabled={busy || !prompt.trim()}>{busy ? 'Understanding…' : 'Begin guided build →'}</button>
      </form>
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
          <button className="primary-action" disabled={busy || !token} onClick={approveRecommendedBrief}>{busy ? (generationStatus ?? 'Preparing the build…') : 'Approve and continue'}</button>
        </div>
        <aside className="build-context-card build-codex-summary">
          <div className="summary-agent"><span className="guide-avatar">C</span><div><p className="eyebrow">Codex understood</p><h3>{reviewSummary}</h3></div></div><p>{reviewReason}</p>
          <div className="assumption-list"><strong>Working assumptions</strong><span>FDM process</span><span>General-use safety class</span><span>Printer selected later</span></div>
          {reviewQuestion ? <div className="blocking-question"><strong>Decision to revisit</strong><p>{reviewQuestion}</p></div> : null}
        </aside>
      </section> : null}

      {step === 'components' && project && robotPath ? <section className="component-first-stage">
        <div className="component-first-heading"><div><p className="eyebrow">Component-first layout</p><h2>These parts define the robot body.</h2><p>Codex removed the unknown battery from Rev A and sized the enclosure around selected compute and motion hardware. You can replace a component later and Ariad will revise the shell.</p></div><span>External 5 V · no battery</span></div>
        <div className="component-first-grid">
          <article><strong>Raspberry Pi Zero 2 W</strong><span>65 × 30 mm board</span><small>Official outline · four M2.5 mounting points</small></article>
          <article><strong>2× Feetech SCS0009</strong><span>23.2 × 12.1 × 25.25 mm each</span><small>Manufacturer envelope · structural chassis cradles</small></article>
          <article><strong>OV5647 camera</strong><span>25 × 24 mm reservation</span><small>Exact supplier board and ribbon still need measurement</small></article>
          <article><strong>MPU-6050 IMU</strong><span>Reserved, not mounted yet</span><small>Select the exact GY-521 board before releasing its clip</small></article>
        </div>
        <div className="component-first-boundary"><strong>Why Ariad pauses here</strong><p>The shell follows these envelopes. It is not generated first and filled with imaginary electronics afterward.</p></div>
        <div className="blueprint-approval-actions"><button className="secondary-action" type="button" onClick={() => setCodexContext('Help me review or replace one of the selected robot components before the shell is designed.')}>Ask Codex to change a component</button><button className="primary-action" type="button" onClick={() => setStep('blueprint')}>Use this hardware layout</button></div>
      </section> : null}

      {step === 'blueprint' && project && robotPath ? <section className="blueprint-approval-stage">
        <div className="blueprint-approval-heading"><div><p className="eyebrow">Component-aware visual blueprint</p><h2>Does this arrangement match what you meant?</h2><p>Check the selected hardware, structural servo chassis, long side limbs, rear service access, and nine-part print layout. CAD dimensions and fit evidence follow.</p></div><span>Layout approved before shell</span></div>
        <AssemblyBlueprint compact />
        <div className="blueprint-approval-actions"><button className="secondary-action" type="button" onClick={() => setCodexContext('Help me review the visual blueprint and describe a practical change before CAD.')}>Ask Codex for a visual change</button><button className="primary-action" type="button" onClick={() => setStep('cad')}>Approve blueprint and inspect CAD</button></div>
      </section> : null}

      {(['components', 'blueprint', 'cad', 'verify', 'slice', 'package'] as SessionStep[]).includes(step) && project ? <details className="build-work-log"><summary>What Codex prepared</summary><div><strong>{planSource === 'codex' ? 'Codex-authored plan' : 'Local deterministic plan'}</strong><p>{designPlan.geometry_strategy}</p><span>{designPlan.critical_features.length} features · {designPlan.assembly_interfaces.length} interfaces · {designPlan.unresolved_questions.length} open decisions</span></div></details> : null}

      {(['cad', 'verify', 'slice', 'package'] as SessionStep[]).includes(step) && project && robotPath ? <RobotCadWorkspace key={step} mode={step as 'cad' | 'verify' | 'slice' | 'package'} onAskCodex={setCodexContext} onContinue={() => setStep(step === 'cad' ? 'verify' : step === 'verify' ? 'slice' : 'package')} /> : null}
      {(['cad', 'verify', 'slice', 'package'] as SessionStep[]).includes(step) && project && liveCad && buildPath === 'live_bracket' ? <LiveBracketWorkspace result={liveCad} key={step} mode={step as 'cad' | 'verify' | 'slice' | 'package'} onAskCodex={setCodexContext} onContinue={() => setStep(step === 'cad' ? 'verify' : step === 'verify' ? 'slice' : 'package')} /> : null}
      {(['cad', 'verify', 'slice', 'package'] as SessionStep[]).includes(step) && project && declarativeCad && buildPath === 'universal' ? <LiveDeclarativeWorkspace result={declarativeCad} key={`${step}-${declarativeCad.generation_id}`} mode={step as 'cad' | 'verify' | 'slice' | 'package'} revising={busy} onRevise={reviseDeclarativeCad} onContinue={() => setStep(step === 'cad' ? 'verify' : step === 'verify' ? 'slice' : 'package')} /> : null}
      {codexContext && project ? <BuildCodexPanel available={codexAvailable} key={codexContext} context={codexContext} projectId={project.project_id} sessionToken={token} onClose={() => setCodexContext(null)} /> : null}

      {error ? <div className="build-error" role="alert">{error}</div> : null}
    </div>
  )
}
