import { useEffect, useState } from 'react'
import {
  Link,
  Navigate,
  RouterProvider,
  createBrowserRouter,
  useParams,
} from 'react-router-dom'

import logoUrl from '../../assets/ariad-fabrication-official-logo.jpg'
import { getRevision, listRevisions } from './api'
import { ArtifactInspector } from './ArtifactInspector'
import type { Finding, RevisionDetail, RevisionSummary, Stage } from './types'

const stageNames: Record<string, string> = {
  brief: 'Brief',
  design: 'Design',
  geometry_validation: 'Geometry validation',
  printability_validation: 'Printability assessment',
  slicing: 'Slicing',
  fabrication_package: 'Fabrication package',
  manufacturing: 'Manufacturing',
}

function readable(value: string | null | undefined): string {
  if (!value) return 'Unavailable'
  return value.replaceAll('_', ' ')
}

function formatBytes(value: number | null): string {
  if (value === null) return 'Size unrecorded'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`
}

function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/" aria-label="Ariad Fabrication home">
          <img src={logoUrl} alt="Ariad Fabrication" />
          <span>
            <strong>Ariad Fabrication</strong>
            <small>Follow the thread from idea to evidence</small>
          </span>
        </Link>
        <div className="boundary-pill" title="This interface has no hardware endpoints">
          Read-only · hardware disconnected
        </div>
      </header>
      <main>{children}</main>
    </div>
  )
}

function Loading({ message }: { message: string }) {
  return <div className="state-panel">{message}</div>
}

function ErrorPanel({ error }: { error: string }) {
  return (
    <div className="state-panel error-panel" role="alert">
      <strong>Evidence could not be loaded</strong>
      <p>{error}</p>
    </div>
  )
}

function RevisionCard({ revision }: { revision: RevisionSummary }) {
  if (revision.availability !== 'available') {
    return (
      <article className="revision-card invalid-card">
        <div className="card-kicker">Persisted revision unavailable</div>
        <h2>{revision.job_id}</h2>
        <p>{revision.error ?? 'The record is malformed or incomplete.'}</p>
      </article>
    )
  }
  return (
    <Link
      className="revision-card"
      to={`/jobs/${encodeURIComponent(revision.job_id)}/revisions/${encodeURIComponent(revision.revision_id)}`}
    >
      <div className="card-kicker">
        {revision.source?.fixture ? 'Interface fixture' : 'Persisted pipeline revision'}
      </div>
      <h2>{revision.title}</h2>
      <div className="metric-row">
        <span>{revision.achieved_evidence_level ?? 'No evidence level'}</span>
        <span>{revision.stage_count} recorded stages</span>
        <span>{revision.warning_count} unresolved warnings</span>
      </div>
      <p>
        Latest recorded state: {stageNames[revision.latest_stage ?? ''] ?? readable(revision.latest_stage)} ·{' '}
        {readable(revision.latest_status)}
      </p>
    </Link>
  )
}

function JourneyIndexPage() {
  const [revisions, setRevisions] = useState<RevisionSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    listRevisions(controller.signal)
      .then((result) => setRevisions(result.revisions))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : 'Unknown API error')
        }
      })
    return () => controller.abort()
  }, [])

  return (
    <AppShell>
      <section className="hero">
        <div>
          <p className="eyebrow">Fabrication Journey · M4</p>
          <h1>Inspect what happened. See what remains unproven.</h1>
          <p>
            Each card comes from a persisted revision. The interface does not calculate fictional
            progress or turn warnings into a printable badge.
          </p>
        </div>
        <div className="hero-boundary">
          <span>Current boundary</span>
          <strong>Digital evidence only</strong>
          <p>No printer control or physical validation is available.</p>
        </div>
      </section>
      <section className="content-section" aria-labelledby="revisions-heading">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Local records</p>
            <h2 id="revisions-heading">Available revisions</h2>
          </div>
        </div>
        {error ? <ErrorPanel error={error} /> : null}
        {!error && revisions === null ? <Loading message="Reading persisted journeys…" /> : null}
        {!error && revisions?.length === 0 ? (
          <div className="state-panel">
            No journey records were found under the configured root. Generate the interface fixture
            or run the Golden Part pipeline.
          </div>
        ) : null}
        <div className="revision-grid">
          {revisions?.map((revision) => (
            <RevisionCard key={`${revision.job_id}/${revision.revision_id}`} revision={revision} />
          ))}
        </div>
      </section>
    </AppShell>
  )
}

function FindingCard({ finding }: { finding: Finding }) {
  return (
    <article className={`finding finding-${finding.severity}`}>
      <div className="finding-heading">
        <strong>{finding.title}</strong>
        <span>{finding.severity}</span>
      </div>
      <p>{finding.evidence}</p>
      {finding.remediation ? <small>Next evidence: {finding.remediation}</small> : null}
    </article>
  )
}

function StageCard({ stage, position }: { stage: Stage; position: number }) {
  return (
    <article className="stage-card">
      <div className="stage-node" aria-hidden="true">
        {position}
      </div>
      <div className="stage-body">
        <div className="stage-heading">
          <div>
            <p className="eyebrow">{stage.evidence_mode} evidence</p>
            <h3>{stageNames[stage.stage] ?? readable(stage.stage)}</h3>
          </div>
          <div className="stage-badges">
            {stage.evidence_level ? <span className="evidence-badge">{stage.evidence_level}</span> : null}
            <span className={`status-badge status-${stage.status}`}>{readable(stage.status)}</span>
          </div>
        </div>
        <p className="stage-summary">{stage.summary || 'No stage summary was recorded.'}</p>
        {stage.error_message ? <div className="stage-error">{stage.error_message}</div> : null}
        {stage.findings.length > 0 ? (
          <div className="finding-list">
            {stage.findings.map((finding) => (
              <FindingCard key={finding.finding_id} finding={finding} />
            ))}
          </div>
        ) : null}
        {stage.artifacts.length > 0 ? (
          <div className="artifact-list">
            <h4>Artifacts</h4>
            {stage.artifacts.map((artifact) => (
              <a
                className={artifact.available ? 'artifact-row' : 'artifact-row artifact-missing'}
                href={artifact.available ? artifact.download_url : undefined}
                key={artifact.artifact_id}
              >
                <span>
                  <strong>{readable(artifact.role)}</strong>
                  <small>
                    {artifact.media_type} · {formatBytes(artifact.size_bytes)} · {artifact.evidence_mode}
                  </small>
                </span>
                <span>{artifact.available ? 'Open' : 'Unavailable'}</span>
              </a>
            ))}
          </div>
        ) : null}
        {stage.events.length > 0 ? (
          <details className="event-log">
            <summary>{stage.events.length} recorded event{stage.events.length === 1 ? '' : 's'}</summary>
            <ol>
              {stage.events.map((event) => (
                <li key={event.event_id}>
                  <span>{event.sequence}</span>
                  <div>
                    <strong>{readable(event.event_type)}</strong>
                    <p>{event.message}</p>
                  </div>
                </li>
              ))}
            </ol>
          </details>
        ) : null}
      </div>
    </article>
  )
}

export function JourneyView({ detail }: { detail: RevisionDetail }) {
  const findings = detail.stages.flatMap((stage) => stage.findings)
  const artifacts = detail.stages.flatMap((stage) => stage.artifacts)
  const warningCount = findings.filter(
    (finding) => !finding.resolved && ['warning', 'error', 'critical'].includes(finding.severity),
  ).length
  const latestEvidence = [...detail.stages]
    .reverse()
    .find((stage) => stage.evidence_level)?.evidence_level
  const previewArtifact = artifacts.find(
    (artifact) =>
      artifact.available &&
      artifact.role === 'preview_model' &&
      artifact.media_type === 'model/gltf-binary',
  )
  const gcodeArtifact = artifacts.find(
    (artifact) =>
      artifact.available &&
      artifact.role === 'gcode' &&
      artifact.media_type === 'text/x.gcode',
  )

  return (
    <AppShell>
      {detail.source.fixture ? (
        <div className="fixture-banner" role="status">
          <strong>INTERFACE FIXTURE</strong>
          <span>No displayed stage is fabrication or physical evidence.</span>
        </div>
      ) : null}
      <section className="detail-header">
        <div>
          <Link className="back-link" to="/">
            ← All revisions
          </Link>
          <p className="eyebrow">Revision {detail.revision.number}</p>
          <h1>{detail.job.title}</h1>
          <p>{detail.job.request}</p>
        </div>
        <div className="evidence-panel">
          <span>Achieved digital level</span>
          <strong>{latestEvidence ?? 'None recorded'}</strong>
          <small>{warningCount} unresolved warning{warningCount === 1 ? '' : 's'}</small>
        </div>
      </section>
      <section className="claim-grid">
        <article>
          <p className="eyebrow">Allowed claim</p>
          <h2>{detail.package?.allowed_claim ?? 'No fabrication-package claim recorded'}</h2>
          <p>
            {detail.package?.claim_boundary ??
              'This revision has no persisted package claim. Its individual stage records remain visible without promotion.'}
          </p>
        </article>
        <article>
          <p className="eyebrow">Hardware boundary</p>
          <h2>Disconnected and read-only</h2>
          <p>
            This application has no upload, heating, movement, recovery, or print-start capability.
          </p>
        </article>
      </section>
      <section className="journey-layout">
        <div className="timeline-column">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Persisted execution trace</p>
              <h2>The fabrication thread</h2>
            </div>
            <span>{detail.manifest_available ? 'Manifest recorded' : 'Manifest unavailable'}</span>
          </div>
          <div className="timeline">
            {detail.stages.map((stage, index) => (
              <StageCard key={stage.stage_run_id} position={index + 1} stage={stage} />
            ))}
          </div>
        </div>
        <aside className="inspector-column">
          <div className="sticky-panel">
            <p className="eyebrow">Inspection surface</p>
            <h2>Model, evidence, and toolpath</h2>
            <ArtifactInspector
              artifacts={artifacts}
              findings={findings}
              gcodeArtifact={gcodeArtifact ?? null}
              inspection={detail.inspection}
              key={detail.revision.revision_id}
              previewArtifact={previewArtifact ?? null}
            />
            <dl>
              <div>
                <dt>Source</dt>
                <dd>{detail.source.label}</dd>
              </div>
              <div>
                <dt>Evidence mode</dt>
                <dd>{detail.source.evidence_mode}</dd>
              </div>
              <div>
                <dt>Physical evidence</dt>
                <dd>{detail.source.physical_evidence_present ? 'Recorded' : 'Not recorded'}</dd>
              </div>
            </dl>
          </div>
        </aside>
      </section>
    </AppShell>
  )
}

function JourneyDetailPage() {
  const { jobId, revisionId } = useParams()
  const [detail, setDetail] = useState<RevisionDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!jobId || !revisionId) return
    const controller = new AbortController()
    getRevision(jobId, revisionId, controller.signal)
      .then(setDetail)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : 'Unknown API error')
        }
      })
    return () => controller.abort()
  }, [jobId, revisionId])

  if (!jobId || !revisionId) return <Navigate to="/" replace />
  if (error) return <AppShell><ErrorPanel error={error} /></AppShell>
  if (!detail) return <AppShell><Loading message="Following the persisted thread…" /></AppShell>
  return <JourneyView detail={detail} />
}

const router = createBrowserRouter([
  { path: '/', element: <JourneyIndexPage /> },
  { path: '/jobs/:jobId/revisions/:revisionId', element: <JourneyDetailPage /> },
  { path: '*', element: <Navigate to="/" replace /> },
])

export default function App() {
  return <RouterProvider router={router} />
}
