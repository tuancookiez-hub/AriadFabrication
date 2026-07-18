import { type FormEvent, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'

import { confirmProjectBrief, getBrowserSession, getProjectDetail, saveProjectDraft } from './api'
import type { ProjectDetail, ProjectDraftRequest } from './types'

const emptyDraft: ProjectDraftRequest = { name: null, purpose: null, part_type: null, size_x_mm: null, size_y_mm: null, size_z_mm: null, material: null, tolerance_mm: null, support_policy: null, manufacturing_process: 'FDM', safety_class: 'general' }

export function ProjectClarifyPage() {
  const { projectId = '' } = useParams()
  const [token, setToken] = useState<string | null>(null)
  const [detail, setDetail] = useState<ProjectDetail | null>(null)
  const [draft, setDraft] = useState<ProjectDraftRequest>(emptyDraft)
  const [saved, setSaved] = useState<string[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [approvalChecked, setApprovalChecked] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    getBrowserSession(controller.signal).then((session) => {
      setToken(session.session_token)
      return getProjectDetail(projectId, session.session_token, controller.signal)
    }).then((result) => {
      setDetail(result)
      if (result.draft) setDraft(result.draft)
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Project could not load.')
    })
    return () => controller.abort()
  }, [projectId])

  function text(name: keyof ProjectDraftRequest, value: string) { setDraft((current) => ({ ...current, [name]: value.trim() ? value : null })) }
  function number(name: keyof ProjectDraftRequest, value: string) { setDraft((current) => ({ ...current, [name]: value ? Number(value) : null })) }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!token || detail?.brief) return
    setError(null)
    try {
      const result = await saveProjectDraft(projectId, draft, token)
      setSaved(result.missing_fields)
      setDetail((current) => current ? { ...current, draft: result } : current)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Draft could not be saved.') }
  }

  async function confirmBrief() {
    if (!token || !approvalChecked) return
    setError(null)
    try {
      const brief = await confirmProjectBrief(projectId, token)
      setDetail((current) => current ? { ...current, brief } : current)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Brief could not be confirmed.') }
  }

  return (
    <>
      <section className="clarify-hero"><p className="eyebrow">Clarify requirements</p><h1 data-route-heading tabIndex={-1}>{detail?.project.title ?? 'Loading project...'}</h1><p>Unknowns stay visible. Saving this form does not confirm the PartSpec or start fabrication.</p></section>
      <form className="clarify-form" onSubmit={submit}>
        <fieldset disabled={Boolean(detail?.brief)}>
        <div className="clarify-grid">
          <label>Name<input value={draft.name ?? ''} onChange={(e) => text('name', e.target.value)} /></label>
          <label>Purpose<input value={draft.purpose ?? ''} onChange={(e) => text('purpose', e.target.value)} /></label>
          <label>Part type<input value={draft.part_type ?? ''} onChange={(e) => text('part_type', e.target.value)} /></label>
          <label>Length (mm)<input min="0.01" step="any" type="number" value={draft.size_x_mm ?? ''} onChange={(e) => number('size_x_mm', e.target.value)} /></label>
          <label>Width (mm)<input min="0.01" step="any" type="number" value={draft.size_y_mm ?? ''} onChange={(e) => number('size_y_mm', e.target.value)} /></label>
          <label>Height (mm)<input min="0.01" step="any" type="number" value={draft.size_z_mm ?? ''} onChange={(e) => number('size_z_mm', e.target.value)} /></label>
          <label>Material<input placeholder="e.g. PLA or PETG" value={draft.material ?? ''} onChange={(e) => text('material', e.target.value)} /></label>
          <label>Tolerance (mm)<input min="0.001" step="any" type="number" value={draft.tolerance_mm ?? ''} onChange={(e) => number('tolerance_mm', e.target.value)} /></label>
          <label>Support policy<select value={draft.support_policy ?? ''} onChange={(e) => text('support_policy', e.target.value)}><option value="">Unknown</option><option value="avoid">Avoid</option><option value="allowed">Allowed</option><option value="required">Required</option></select></label>
          <label>Process<input value={draft.manufacturing_process ?? ''} onChange={(e) => text('manufacturing_process', e.target.value)} /></label>
          <label>Safety class<select value={draft.safety_class ?? ''} onChange={(e) => text('safety_class', e.target.value)}><option value="general">General</option><option value="caution">Caution</option><option value="safety_critical">Safety critical</option></select></label>
        </div>
        {error ? <div className="chat-error" role="alert">{error}</div> : null}
        {saved ? <div className="draft-status" role="status">{saved.length ? `Draft saved. Still missing: ${saved.join(', ')}.` : 'Draft complete and ready for a separate confirmation. No R0 evidence exists yet.'}</div> : null}
        <button className="primary-action" type="submit">Save clarification draft</button>
        </fieldset>
      </form>
      <section className="brief-confirmation" aria-labelledby="brief-confirmation-title">
        <h2 id="brief-confirmation-title">Confirm the manufacturing brief</h2>
        {detail?.brief ? <p role="status">R0 Brief confirmed. This project is ready for Design. Fabrication has not started.</p> : <>
          <p>This records the displayed requirements as your approved PartSpec. It still does not generate CAD, slice, print, or contact hardware.</p>
          <label><input type="checkbox" checked={approvalChecked} onChange={(event) => setApprovalChecked(event.target.checked)} /> I reviewed these requirements and approve them for Design.</label>
          <button className="primary-action" type="button" disabled={detail?.draft?.status !== 'ready_for_confirmation' || !approvalChecked} onClick={confirmBrief}>Confirm PartSpec and create R0 Brief</button>
        </>}
      </section>
    </>
  )
}
