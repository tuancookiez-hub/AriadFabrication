import { fireEvent, render, screen, within } from '@testing-library/react'
import { Link, MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { JourneyView, RevisionListingStatus, RouteAccessibility } from './App'
import { EvidenceInspector } from './EvidenceInspector'
import type { Artifact, Inspection, RevisionDetail, RevisionListWindow } from './types'

const reportArtifact: Artifact = {
  artifact_id: 'artifact_geometry_report',
  role: 'geometry_validation_report',
  media_type: 'application/json',
  checksum_sha256: 'a'.repeat(64),
  size_bytes: 512,
  producer: 'fixture',
  producer_version: '1.0.0',
  evidence_mode: 'fixture',
  stage_run_id: 'run_fixture_printability',
  available: true,
  download_url: '/fixture/geometry-report',
  metadata: { classification: 'interface_fixture' },
}

const detail: RevisionDetail = {
  schema_version: '1.13.0',
  capabilities: { read_only: false, project_intent_persistence: true, fabrication_execution: false, hardware_actions: false },
  source: {
    kind: 'interface_fixture',
    label: 'INTERFACE FIXTURE — no fabrication or physical evidence',
    evidence_mode: 'fixture',
    fixture: true,
    physical_evidence_present: false,
  },
  manifest_available: true,
  job: {
    job_id: 'job_interface_fixture',
    title: 'OpenGrow interface fixture',
    request: 'Replay records for the browser.',
    status: 'completed',
    created_at: '2026-07-16T08:00:00+00:00',
    updated_at: '2026-07-16T08:00:00+00:00',
    metadata: {},
  },
  revision: {
    revision_id: 'rev_interface_fixture',
    number: 1,
    parent_revision_id: null,
    reason: 'Interface fixture',
    created_at: '2026-07-16T08:00:00+00:00',
    spec: {},
  },
  stages: [
    {
      stage_run_id: 'run_fixture_printability',
      stage: 'printability_validation',
      status: 'passed_with_warnings',
      attempt: 1,
      evidence_mode: 'fixture',
      evidence_level: 'R3',
      tool: { name: 'fixture', version: '1.0.0' },
      started_at: '2026-07-16T08:00:00+00:00',
      completed_at: '2026-07-16T08:00:00+00:00',
      summary: 'Fixture warning is retained.',
      error_message: null,
      events: [],
      findings: [
        {
          finding_id: 'finding_fixture',
          code: 'fixture.physical_unknown',
          title: 'Physical behavior remains unknown',
          severity: 'warning',
          evidence: 'No physical measurement exists.',
          evidence_mode: 'fixture',
          remediation: 'Print and measure later.',
          affected_geometry: null,
          resolved: false,
          resolution: null,
          data: {},
        },
      ],
      artifacts: [reportArtifact],
      decisions: [],
      approvals: [],
    },
  ],
  package: null,
  inspection: {
    features: [
      {
        feature_id: 'stake_bore',
        kind: 'cylindrical_mating_bore',
        dimensions_mm: { diameter: 12.6, depth: 50 },
        quantity: 1,
        tolerance_mm: 0.2,
        required: true,
        notes: 'Fixture requirement only.',
        source: 'persisted_revision_spec',
        fixture: true,
      },
    ],
    reports: [
      {
        report_kind: 'geometry',
        title: 'Geometry validation',
        artifact: {
          artifact_id: reportArtifact.artifact_id,
          role: reportArtifact.role,
          checksum_sha256: reportArtifact.checksum_sha256,
          size_bytes: reportArtifact.size_bytes ?? 0,
          producer: reportArtifact.producer,
          producer_version: reportArtifact.producer_version,
          evidence_mode: 'fixture',
          checksum_verified: true,
        },
        schema_version: '1.0.0-interface-fixture',
        status: 'passed',
        passed: true,
        evidence_level: 'R2',
        claim_boundary: 'Fixture report only.',
        measurements: { stake_bore_diameter_mm: 12.6 },
        checks: [
          {
            check_id: 'stake_bore_diameter',
            category: 'feature',
            description: 'Fixture bore matches the fixture requirement.',
            passed: true,
            actual: 12.6,
            requirement: 12.6,
            tolerance_mm: 0.2,
            remediation: null,
          },
        ],
        messages: [],
      },
    ],
    profiles: [],
    unavailable: [],
    max_json_bytes: 2 * 1024 * 1024,
    claim_boundary: 'Fixture values are replayed without rerunning validation.',
  },
}

function RouteFocusFixture() {
  const location = useLocation()
  return (
    <>
      <RouteAccessibility />
      <Link to="/next">Open next route</Link>
      <h1 data-route-heading tabIndex={-1}>
        {location.pathname === '/next' ? 'Next route' : 'Initial route'}
      </h1>
    </>
  )
}

describe('RouteAccessibility', () => {
  it('moves focus to the new route heading without stealing initial focus', () => {
    render(
      <MemoryRouter>
        <RouteFocusFixture />
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { name: 'Initial route' })).not.toHaveFocus()
    fireEvent.click(screen.getByRole('link', { name: 'Open next route' }))
    expect(screen.getByRole('heading', { name: 'Next route' })).toHaveFocus()
  })
})

describe('JourneyView', () => {
  it('keeps fixture and hardware boundaries visible', () => {
    render(
      <MemoryRouter>
        <JourneyView detail={detail} />
      </MemoryRouter>,
    )

    expect(screen.getByText('INTERFACE FIXTURE')).toBeInTheDocument()
    expect(screen.getByText('No fabrication-package claim recorded')).toBeInTheDocument()
    expect(screen.getByText('Physical behavior remains unknown')).toBeInTheDocument()
    expect(screen.getByText('Disconnected and read-only')).toBeInTheDocument()
    expect(screen.getByText('Persisted evidence replay')).toBeInTheDocument()
    expect(screen.getByText('Verified before parsing')).toBeInTheDocument()
    expect(screen.getByText(/does not highlight exact geometry/i)).toBeInTheDocument()
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main-content')
    expect(screen.getByRole('link', { name: 'Skip to main content' })).toHaveAttribute(
      'href',
      '#main-content',
    )
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'OpenGrow interface fixture',
    )
    expect(screen.getByRole('button', { name: /stake bore diameter.*passed/i })).toBeInTheDocument()
    expect(document.title).toBe('OpenGrow interface fixture — Ariad Fabrication')
    fireEvent.click(screen.getByRole('button', { name: 'Features 1' }))
    expect(screen.getByText(/requested feature from the revision specification/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Artifacts 1' }))
    expect(screen.getByText(reportArtifact.checksum_sha256)).toBeInTheDocument()
    const evidenceTab = screen.getByRole('tab', { name: 'Evidence' })
    fireEvent.keyDown(evidenceTab, { key: 'ArrowLeft' })
    expect(screen.getByRole('tab', { name: 'Model' })).toHaveFocus()
    expect(screen.getByRole('tab', { name: 'Model' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('No GLB preview recorded')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'Toolpath' }))
    expect(screen.getByText('No G-code recorded')).toBeInTheDocument()
    expect(screen.queryByText('Printable')).not.toBeInTheDocument()
  })

  it('does not expose an unavailable artifact as an actionable link', () => {
    const unavailableDetail: RevisionDetail = {
      ...detail,
      stages: [
        {
          ...detail.stages[0],
          artifacts: [{ ...reportArtifact, available: false }],
        },
      ],
      inspection: {
        ...detail.inspection,
        reports: [],
      },
    }

    render(
      <MemoryRouter>
        <JourneyView detail={unavailableDetail} />
      </MemoryRouter>,
    )

    expect(
      screen.queryByRole('link', { name: 'Open geometry validation report artifact' }),
    ).not.toBeInTheDocument()
    expect(screen.getByText('Unavailable').closest('[aria-disabled="true"]')).not.toBeNull()
  })

  it('keeps a corrupt inspection source unavailable instead of presenting its checks', () => {
    const inspection: Inspection = {
      features: [],
      reports: [],
      profiles: [],
      unavailable: [
        {
          role: 'geometry_validation_report',
          artifact_id: 'artifact_geometry_report',
          checksum_sha256: 'b'.repeat(64),
          reason: 'checksum_mismatch',
          message: 'The recorded report checksum does not match.',
        },
      ],
      max_json_bytes: 2 * 1024 * 1024,
      claim_boundary: 'Only verified reports may be parsed.',
    }

    render(<EvidenceInspector artifacts={[]} findings={[]} inspection={inspection} />)

    expect(screen.getByText('Inspection sources unavailable')).toBeInTheDocument()
    expect(screen.getByText(/recorded report checksum does not match/i)).toBeInTheDocument()
    expect(screen.queryByText('Passed')).not.toBeInTheDocument()
  })
})

describe('RevisionListingStatus', () => {
  it('discloses incomplete discovery and pages only within observed candidates', () => {
    const window: RevisionListWindow = {
      discovery_complete: false,
      snapshot_consistent: false,
      ordering: 'job_id_revision_id_ascending',
      directory_entries_examined: 12,
      observed_candidate_count: 6,
      offset: 2,
      limit: 2,
      returned_count: 2,
      observed_omitted_count: 4,
      next_offset: 4,
      truncation_reasons: ['candidate_limit', 'window_limit'],
      max_directory_entries: 5_000,
      max_candidates: 6,
      error: null,
      claim_boundary:
        'Pages are not a snapshot. Incomplete discovery is not evidence that omitted revisions do not exist.',
    }
    const onOffsetChange = vi.fn()

    const { rerender } = render(
      <RevisionListingStatus window={window} onOffsetChange={onOffsetChange} />,
    )

    const listing = screen.getByLabelText('Revision discovery status')
    expect(listing).toHaveTextContent('Bounded discovery incomplete')
    expect(listing).toHaveTextContent('more may exist')
    expect(listing).toHaveTextContent('candidate ceiling')
    expect(listing).toHaveTextContent('not a snapshot')
    expect(listing).toHaveTextContent('not evidence')
    fireEvent.click(within(listing).getByRole('button', { name: 'Previous' }))
    expect(onOffsetChange).toHaveBeenLastCalledWith(0)
    fireEvent.click(within(listing).getByRole('button', { name: 'Next' }))
    expect(onOffsetChange).toHaveBeenLastCalledWith(4)

    rerender(
      <RevisionListingStatus
        window={{ ...window, offset: 500, returned_count: 0, next_offset: null }}
        onOffsetChange={onOffsetChange}
      />,
    )
    expect(listing).toHaveTextContent('No revisions returned from 6 observed candidates.')
    expect(listing).not.toHaveTextContent('0 to 500')
  })
})
