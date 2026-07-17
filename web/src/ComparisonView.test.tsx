import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { ComparisonView } from './ComparisonView'
import type { ComparisonRevision, RevisionComparison } from './types'

const baseRevision: ComparisonRevision = {
  job_id: 'job_interface_fixture',
  revision_id: 'rev_interface_fixture',
  revision_number: 1,
  parent_revision_id: null,
  title: 'OpenGrow interface fixture',
  job_status: 'completed',
  source_kind: 'interface_fixture',
  source_label: 'INTERFACE FIXTURE — no fabrication or physical evidence',
  fixture: true,
  physical_evidence_present: false,
  achieved_evidence_level: 'R4',
  package_status: 'fixture',
  package_evidence_level: null,
  allowed_claim: 'Interface fixture only — no fabrication evidence.',
  normalized_record_count: 66,
  compared_record_count: 66,
  omitted_record_count: 0,
}

const comparison: RevisionComparison = {
  schema_version: '1.9.0',
  capabilities: { read_only: true, hardware_actions: false },
  base: baseRevision,
  candidate: {
    ...baseRevision,
    revision_id: 'rev_interface_fixture_v2',
    revision_number: 2,
    parent_revision_id: 'rev_interface_fixture',
  },
  relationship: 'parent_to_child',
  complete: true,
  total_change_count: 1,
  returned_change_count: 1,
  omitted_change_count: 0,
  incomplete_value_count: 0,
  summaries: [{ area: 'feature', added: 0, removed: 0, changed: 1 }],
  changes: [
    {
      area: 'feature',
      record_key: 'stake_bore',
      label: 'stake bore',
      change: 'changed',
      base_value: { dimensions_mm: { diameter: 12.6 } },
      candidate_value: { dimensions_mm: { diameter: 12.8 } },
      detail_complete: true,
      boundary: null,
    },
  ],
  max_changes: 1000,
  max_value_bytes: 65536,
  max_records_per_revision: 10000,
  claim_boundary:
    'This comparison does not rerun CAD, validation, slicing, simulation, or physical work.',
}

describe('ComparisonView', () => {
  it('keeps fixture, physical, and rerun boundaries beside the diff', () => {
    render(
      <MemoryRouter>
        <ComparisonView comparison={comparison} />
      </MemoryRouter>,
    )

    expect(screen.getByText('INTERFACE FIXTURE COMPARISON')).toBeInTheDocument()
    expect(screen.getByText('Parent to child')).toBeInTheDocument()
    expect(screen.getByText('A diff is not a new validation run.')).toBeInTheDocument()
    expect(screen.getAllByText('Not recorded')).toHaveLength(2)
    expect(screen.queryByText('Printable')).not.toBeInTheDocument()

    fireEvent.click(screen.getByText('stake bore'))
    expect(screen.getByText(/12.6/)).toBeInTheDocument()
    expect(screen.getByText(/12.8/)).toBeInTheDocument()
  })

  it('does not present a bounded response as complete', () => {
    render(
      <MemoryRouter>
        <ComparisonView
          comparison={{
            ...comparison,
            complete: false,
            omitted_change_count: 2,
            incomplete_value_count: 1,
            base: { ...comparison.base, omitted_record_count: 3 },
          }}
        />
      </MemoryRouter>,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('Some comparison detail is incomplete.')
    expect(screen.getByText(/2 change rows omitted/)).toBeInTheDocument()
    expect(screen.getByText(/3 normalized records omitted/)).toBeInTheDocument()
  })
})
