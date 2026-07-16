import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { JourneyView, RevisionListingStatus } from './App'
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
  schema_version: '1.5.0',
  capabilities: { read_only: true, hardware_actions: false },
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
    fireEvent.click(screen.getByRole('button', { name: 'Features 1' }))
    expect(screen.getByText(/requested feature from the revision specification/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Artifacts 1' }))
    expect(screen.getByText(reportArtifact.checksum_sha256)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Model' }))
    expect(screen.getByText('No GLB preview recorded')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Toolpath' }))
    expect(screen.getByText('No G-code recorded')).toBeInTheDocument()
    expect(screen.queryByText('Printable')).not.toBeInTheDocument()
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
