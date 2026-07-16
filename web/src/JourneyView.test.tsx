import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { JourneyView } from './App'
import type { RevisionDetail } from './types'

const detail: RevisionDetail = {
  schema_version: '1.0.0',
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
      artifacts: [],
      decisions: [],
      approvals: [],
    },
  ],
  package: null,
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
    expect(screen.getByText('No GLB preview recorded')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Toolpath' }))
    expect(screen.getByText('No G-code recorded')).toBeInTheDocument()
    expect(screen.queryByText('Printable')).not.toBeInTheDocument()
  })
})
