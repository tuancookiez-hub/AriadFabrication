import { type FormEvent, useEffect, useRef, useState } from 'react'
import {
  Link,
  Navigate,
  Outlet,
  RouterProvider,
  createBrowserRouter,
  useLocation,
  useNavigate,
  useParams,
} from 'react-router-dom'

import logoUrl from '../../assets/ariad-fabrication-official-logo-v2.png'
import { getLocalCodexStatus, getRevision, getRevisionComparison, listRevisions } from './api'
import { ArtifactInspector } from './ArtifactInspector'
import { ComparisonView } from './ComparisonView'
import { CodexChatPage } from './CodexChatPage'
import { ProjectsPage } from './ProjectsPage'
import { ProjectClarifyPage } from './ProjectClarifyPage'
import { NewIdeaPage } from './NewIdeaPage'
import { AssemblyPage } from './AssemblyPage'
import { BuildSessionPage } from './BuildSessionPage'
import type {
  Finding,
  RevisionComparison,
  RevisionDetail,
  RevisionListResponse,
  RevisionListWindow,
  RevisionSummary,
  Stage,
  LocalCodexStatus,
} from './types'

const REVISION_LIST_LIMIT = 100

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

function pageDocumentTitle(pageTitle: string): string {
  return pageTitle === 'Ariad Fabrication Journey'
    ? pageTitle
    : `${pageTitle} — Ariad Fabrication`
}

export function RouteAccessibility() {
  const location = useLocation()
  const previousLocation = useRef(location.key)

  useEffect(() => {
    if (previousLocation.current === location.key) return
    previousLocation.current = location.key
    const target =
      document.querySelector<HTMLElement>('[data-route-heading]') ??
      document.getElementById('main-content')
    target?.focus()
  }, [location.key])

  return null
}

function AppShell({
  children,
  pageTitle,
}: {
  children: React.ReactNode
  pageTitle: string
}) {
  const [codex, setCodex] = useState<LocalCodexStatus | null>(null)
  const location = useLocation()
  const navClass = (path: string) => `nav-item${location.pathname === path ? ' nav-item-active' : ''}`

  useEffect(() => {
    document.title = pageDocumentTitle(pageTitle)
  }, [pageTitle])

  useEffect(() => {
    const controller = new AbortController()
    getLocalCodexStatus(controller.signal).then(setCodex).catch(() => setCodex(null))
    return () => controller.abort()
  }, [])

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <aside className="app-sidebar" aria-label="Ariad workspace navigation">
        <Link className="brand" to="/build" aria-label="Ariad Fabrication home">
          <img src={logoUrl} alt="Ariad Fabrication" />
        </Link>
        <nav className="primary-navigation" aria-label="Primary navigation">
          <Link className={navClass('/build')} to="/build"><span aria-hidden="true">＋</span> Make something</Link>
          <Link className={navClass('/projects')} to="/projects"><span aria-hidden="true">▤</span> My builds</Link>
          <Link className={navClass('/chat')} to="/chat"><span aria-hidden="true">◌</span> Ask Codex</Link>
          <Link className={navClass('/evidence')} to="/evidence"><span aria-hidden="true">◇</span> Technical evidence</Link>
        </nav>
        <div className="sidebar-status">
          <span className="status-avatar" aria-hidden="true">A</span>
          <span>
            <strong>Codex</strong>
            <small>
              <i /> {codex === null ? 'Checking local agent…' : codex.conversation_available ? 'Local agent ready' : 'Local conversation unavailable'}
            </small>
          </span>
        </div>
      </aside>
      <div className="workspace-shell">
        <header className="topbar">
          <div className="project-context"><small>Ariad Fabrication</small><strong>Make something useful</strong></div>
          <div className="topbar-actions">
            <div className={`system-pill codex-${codex?.status ?? 'checking'}`}>
              <i /> {codex === null ? 'Checking Codex…' : codex.conversation_available ? 'Codex available' : 'Codex unavailable'}
            </div>
            <Link className="new-project-button" to="/build?new=1">+ New build</Link>
        <div className="boundary-pill">
        Hardware off
        </div>
          </div>
        </header>
        <main id="main-content" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  )
}

function Loading({ message }: { message: string }) {
  return (
    <div className="state-panel" role="status" aria-live="polite">
      {message}
    </div>
  )
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
        <h3>{revision.job_id}</h3>
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
      <h3>{revision.title}</h3>
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

function revisionKey(revision: RevisionSummary): string {
  return `${revision.job_id}::${revision.revision_id}`
}

export function ComparisonLauncher({ revisions }: { revisions: RevisionSummary[] }) {
  const navigate = useNavigate()
  const child = revisions.find(
    (revision) =>
      revision.parent_revision_id !== null &&
      revisions.some(
        (candidate) =>
          candidate.job_id === revision.job_id &&
          candidate.revision_id === revision.parent_revision_id,
      ),
  )
  const parent = child
    ? revisions.find(
        (revision) =>
          revision.job_id === child.job_id && revision.revision_id === child.parent_revision_id,
      )
    : undefined
  const [baseKey, setBaseKey] = useState(revisionKey(parent ?? revisions[0]!))
  const [candidateKey, setCandidateKey] = useState(
    revisionKey(child ?? revisions[1] ?? revisions[0]!),
  )

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const base = revisions.find((revision) => revisionKey(revision) === baseKey)
    const candidate = revisions.find((revision) => revisionKey(revision) === candidateKey)
    if (!base || !candidate) return
    navigate(
      `/compare/${encodeURIComponent(base.job_id)}/${encodeURIComponent(base.revision_id)}` +
        `/${encodeURIComponent(candidate.job_id)}/${encodeURIComponent(candidate.revision_id)}`,
    )
  }

  function swap() {
    setBaseKey(candidateKey)
    setCandidateKey(baseKey)
  }

  return (
    <form className="comparison-launcher" onSubmit={submit}>
      <div>
        <p className="eyebrow">Revision lens</p>
        <h3>Compare persisted evidence</h3>
        <p>
          Choose from this displayed page and compare normalized requirement and evidence changes
          without rerunning CAD, validators, or a slicer.
        </p>
      </div>
      <label>
        <span>Base revision</span>
        <select value={baseKey} onChange={(event) => setBaseKey(event.target.value)}>
          {revisions.map((revision) => (
            <option key={`base:${revisionKey(revision)}`} value={revisionKey(revision)}>
              Revision {revision.revision_number ?? '?'} · {revision.title ?? revision.revision_id}
            </option>
          ))}
        </select>
      </label>
      <button className="swap-button" type="button" onClick={swap}>
        Swap
      </button>
      <label>
        <span>Candidate revision</span>
        <select value={candidateKey} onChange={(event) => setCandidateKey(event.target.value)}>
          {revisions.map((revision) => (
            <option key={`candidate:${revisionKey(revision)}`} value={revisionKey(revision)}>
              Revision {revision.revision_number ?? '?'} · {revision.title ?? revision.revision_id}
            </option>
          ))}
        </select>
      </label>
      <button className="compare-button" type="submit">
        Compare records
      </button>
    </form>
  )
}

export function RevisionListingStatus({
  window,
  onOffsetChange,
}: {
  window: RevisionListWindow
  onOffsetChange: (offset: number) => void
}) {
  const rangeLabel =
    window.returned_count === 0
      ? `No revisions returned from ${window.observed_candidate_count} observed candidates.`
      : `Showing observed revisions ${window.offset + 1} to ${window.offset + window.returned_count} of ${window.observed_candidate_count}.`
  const previousOffset = Math.max(0, window.offset - window.limit)
  const reasonLabels: Record<RevisionListWindow['truncation_reasons'][number], string> = {
    directory_entry_limit: 'directory-entry ceiling',
    candidate_limit: 'candidate ceiling',
    window_limit: 'page window',
    filesystem_error: 'filesystem error',
  }

  return (
    <section
      className={`revision-listing-status${window.discovery_complete ? '' : ' listing-incomplete'}`}
      aria-label="Revision discovery status"
    >
      <div role="status" aria-live="polite">
        <p className="eyebrow">
          {window.discovery_complete ? 'Bounded discovery complete' : 'Bounded discovery incomplete'}
        </p>
        <strong>{rangeLabel}</strong>
        {window.discovery_complete ? (
          <p>
            Discovery examined {window.directory_entries_examined} directory entries within the
            configured ceilings.
          </p>
        ) : (
          <p>
            Discovery stopped at a safety boundary after observing at least{' '}
            {window.observed_candidate_count} candidate revisions; more may exist.
          </p>
        )}
        {window.truncation_reasons.length > 0 ? (
          <p className="listing-reasons">
            Active limits:{' '}
            {window.truncation_reasons.map((reason) => reasonLabels[reason]).join(', ')}.
          </p>
        ) : null}
        {window.error ? <p className="listing-error">{window.error}</p> : null}
        <small>{window.claim_boundary}</small>
      </div>
      <nav className="listing-pagination" aria-label="Observed revision pages">
        <button
          type="button"
          disabled={window.offset === 0}
          onClick={() => onOffsetChange(previousOffset)}
        >
          Previous
        </button>
        <button
          type="button"
          disabled={window.next_offset === null}
          onClick={() => {
            if (window.next_offset !== null) onOffsetChange(window.next_offset)
          }}
        >
          Next
        </button>
      </nav>
    </section>
  )
}

function JourneyIndexPage() {
  const [offset, setOffset] = useState(0)
  const [load, setLoad] = useState<{
    offset: number
    listing: RevisionListResponse | null
    error: string | null
  }>({ offset: -1, listing: null, error: null })

  useEffect(() => {
    const controller = new AbortController()
    listRevisions(offset, REVISION_LIST_LIMIT, controller.signal)
      .then((result) => setLoad({ offset, listing: result, error: null }))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setLoad({
            offset,
            listing: null,
            error: reason instanceof Error ? reason.message : 'Unknown API error',
          })
        }
      })
    return () => controller.abort()
  }, [offset])

  const listing = load.offset === offset ? load.listing : null
  const error = load.offset === offset ? load.error : null
  const revisions = listing?.revisions ?? null
  const emptyRoot =
    listing?.window.discovery_complete === true &&
    listing.window.observed_candidate_count === 0
  const availableRevisions =
    revisions?.filter((revision) => revision.availability === 'available') ?? []

  return (
    <AppShell pageTitle="Ariad Fabrication Journey">
      <section className="hero">
        <div>
          <p className="eyebrow">Advanced technical records</p>
          <h1 data-route-heading tabIndex={-1}>Evidence behind each build.</h1>
          <p>
            Inspect persisted revisions, digital checks, and the limits that remain unproven.
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
            <p className="eyebrow">For technical review</p>
            <h2 id="revisions-heading">Recorded revisions</h2>
          </div>
        </div>
        {error ? <ErrorPanel error={error} /> : null}
        {!error && listing === null ? <Loading message="Reading persisted journeys…" /> : null}
        {!error && listing ? (
          <RevisionListingStatus window={listing.window} onOffsetChange={setOffset} />
        ) : null}
        {!error && emptyRoot ? (
          <div className="state-panel">
            No journey records were found under the configured root. Generate the interface fixture
            or run the Golden Part pipeline.
          </div>
        ) : null}
        {availableRevisions.length >= 2 ? (
          <ComparisonLauncher revisions={availableRevisions} />
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
              artifact.available ? (
                <a
                  aria-label={`Open ${readable(artifact.role)} artifact`}
                  className="artifact-row"
                  href={artifact.download_url}
                  key={artifact.artifact_id}
                >
                  <span>
                    <strong>{readable(artifact.role)}</strong>
                    <small>
                      {artifact.media_type} · {formatBytes(artifact.size_bytes)} · {artifact.evidence_mode}
                    </small>
                  </span>
                  <span>Open</span>
                </a>
              ) : (
                <div
                  aria-disabled="true"
                  className="artifact-row artifact-missing"
                  key={artifact.artifact_id}
                >
                  <span>
                    <strong>{readable(artifact.role)}</strong>
                    <small>
                      {artifact.media_type} · {formatBytes(artifact.size_bytes)} · {artifact.evidence_mode}
                    </small>
                  </span>
                  <span>Unavailable</span>
                </div>
              )
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
    <AppShell pageTitle={detail.job.title}>
      {detail.source.fixture ? (
        <div className="fixture-banner" role="status">
          <strong>INTERFACE FIXTURE</strong>
          <span>No displayed stage is fabrication or physical evidence.</span>
        </div>
      ) : null}
      <section className="detail-header">
        <div>
          <Link className="back-link" to="/evidence">
            ← All revisions
          </Link>
          <p className="eyebrow">Revision {detail.revision.number}</p>
          <h1 data-route-heading tabIndex={-1}>{detail.job.title}</h1>
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
  if (error) return <AppShell pageTitle="Revision unavailable"><ErrorPanel error={error} /></AppShell>
  if (!detail) return <AppShell pageTitle="Loading revision"><Loading message="Following the persisted thread…" /></AppShell>
  return <JourneyView detail={detail} />
}

function RevisionComparisonPage() {
  const { baseJobId, baseRevisionId, candidateJobId, candidateRevisionId } = useParams()
  const [comparison, setComparison] = useState<RevisionComparison | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!baseJobId || !baseRevisionId || !candidateJobId || !candidateRevisionId) return
    const controller = new AbortController()
    getRevisionComparison(
      baseJobId,
      baseRevisionId,
      candidateJobId,
      candidateRevisionId,
      controller.signal,
    )
      .then(setComparison)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : 'Unknown API error')
        }
      })
    return () => controller.abort()
  }, [baseJobId, baseRevisionId, candidateJobId, candidateRevisionId])

  if (!baseJobId || !baseRevisionId || !candidateJobId || !candidateRevisionId) {
    return <Navigate to="/" replace />
  }
  if (error) return <AppShell pageTitle="Comparison unavailable"><ErrorPanel error={error} /></AppShell>
  if (!comparison) return <AppShell pageTitle="Loading comparison"><Loading message="Comparing persisted records…" /></AppShell>
  return <AppShell pageTitle="Revision comparison"><ComparisonView comparison={comparison} /></AppShell>
}

const router = createBrowserRouter([
  {
    element: (
      <>
        <RouteAccessibility />
        <Outlet />
      </>
    ),
    children: [
      { path: '/', element: <Navigate to="/build" replace /> },
      { path: '/evidence', element: <JourneyIndexPage /> },
      { path: '/new', element: <AppShell pageTitle="New fabrication idea"><NewIdeaPage /></AppShell> },
      { path: '/build', element: <AppShell pageTitle="Guided Build Session"><BuildSessionPage /></AppShell> },
      { path: '/chat', element: <AppShell pageTitle="Conversation with Codex"><CodexChatPage /></AppShell> },
      { path: '/projects', element: <AppShell pageTitle="Confirmed project intents"><ProjectsPage /></AppShell> },
      { path: '/assembly', element: <AppShell pageTitle="Robot assembly foundation"><AssemblyPage /></AppShell> },
      { path: '/projects/:projectId', element: <AppShell pageTitle="Clarify project requirements"><ProjectClarifyPage /></AppShell> },
      { path: '/jobs/:jobId/revisions/:revisionId', element: <JourneyDetailPage /> },
      {
        path: '/compare/:baseJobId/:baseRevisionId/:candidateJobId/:candidateRevisionId',
        element: <RevisionComparisonPage />,
      },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
])

export default function App() {
  return <RouterProvider router={router} />
}
