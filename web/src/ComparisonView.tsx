import { Link } from 'react-router-dom'

import type {
  ComparisonChange,
  ComparisonRevision,
  RevisionComparison,
} from './types'

const relationshipLabels: Record<RevisionComparison['relationship'], string> = {
  same_revision: 'Same persisted revision',
  parent_to_child: 'Parent to child',
  child_to_parent: 'Child to parent',
  same_job: 'Revisions from the same job',
  unrelated: 'Unrelated jobs',
}

function readable(value: string): string {
  return value.replaceAll('_', ' ')
}

function RevisionSide({
  label,
  revision,
}: {
  label: 'Base' | 'Candidate'
  revision: ComparisonRevision
}) {
  return (
    <article className="comparison-revision">
      <div className="comparison-revision-heading">
        <div>
          <p className="eyebrow">{label} revision</p>
          <h2>Revision {revision.revision_number}</h2>
        </div>
        <span className={revision.fixture ? 'fixture-chip' : 'persisted-chip'}>
          {revision.fixture ? 'Fixture' : 'Runtime record'}
        </span>
      </div>
      <p>{revision.title}</p>
      <code>{revision.job_id}/{revision.revision_id}</code>
      <dl>
        <div>
          <dt>Evidence level</dt>
          <dd>{revision.achieved_evidence_level ?? 'None recorded'}</dd>
        </div>
        <div>
          <dt>Package</dt>
          <dd>{revision.package_status ?? 'Unavailable'}</dd>
        </div>
        <div>
          <dt>Physical evidence</dt>
          <dd>{revision.physical_evidence_present ? 'Recorded' : 'Not recorded'}</dd>
        </div>
        <div>
          <dt>Compared records</dt>
          <dd>
            {revision.compared_record_count} / {revision.normalized_record_count}
          </dd>
        </div>
      </dl>
      <p className="comparison-claim">
        {revision.allowed_claim ?? 'No fabrication-package claim was recorded.'}
      </p>
    </article>
  )
}

function ChangeValue({
  label,
  value,
}: {
  label: string
  value: ComparisonChange['base_value']
}) {
  return (
    <div className="comparison-value">
      <strong>{label}</strong>
      {value === null ? (
        <p>Record not present in this revision.</p>
      ) : (
        <pre>{JSON.stringify(value, null, 2)}</pre>
      )}
    </div>
  )
}

function ChangeRow({ change }: { change: ComparisonChange }) {
  return (
    <details className="comparison-change">
      <summary>
        <span className={`change-kind change-kind-${change.change}`}>{change.change}</span>
        <span>
          <strong>{change.label}</strong>
          <small>{readable(change.area)} · {change.record_key}</small>
        </span>
      </summary>
      {change.boundary ? <div className="comparison-limit-note">{change.boundary}</div> : null}
      <div className="comparison-values">
        <ChangeValue label="Base value" value={change.base_value} />
        <ChangeValue label="Candidate value" value={change.candidate_value} />
      </div>
    </details>
  )
}

export function ComparisonView({ comparison }: { comparison: RevisionComparison }) {
  const recordOmissions =
    comparison.base.omitted_record_count + comparison.candidate.omitted_record_count

  return (
    <>
      {comparison.base.fixture || comparison.candidate.fixture ? (
        <div className="fixture-banner" role="status">
          <strong>INTERFACE FIXTURE COMPARISON</strong>
          <span>These differences demonstrate presentation, not fabrication evidence.</span>
        </div>
      ) : null}
      <section className="comparison-header">
        <div>
          <Link className="back-link" to="/">
            ← All revisions
          </Link>
          <p className="eyebrow">Persisted revision comparison</p>
          <h1>What changed between the records?</h1>
          <p>
            The server normalized and compared recorded requirements and evidence. The browser is
            displaying that result; it did not rerun any fabrication stage.
          </p>
        </div>
        <div className="comparison-status">
          <span>{relationshipLabels[comparison.relationship]}</span>
          <strong>{comparison.total_change_count} observed changes</strong>
          <small>{comparison.complete ? 'Full comparison detail returned' : 'Comparison is bounded'}</small>
        </div>
      </section>

      {!comparison.complete ? (
        <div className="comparison-warning" role="alert">
          <strong>Some comparison detail is incomplete.</strong>
          <span>
            {comparison.omitted_change_count} change rows omitted · {comparison.incomplete_value_count}{' '}
            oversized values · {recordOmissions} normalized records omitted
          </span>
        </div>
      ) : null}

      <section className="comparison-revisions" aria-label="Compared revisions">
        <RevisionSide label="Base" revision={comparison.base} />
        <RevisionSide label="Candidate" revision={comparison.candidate} />
      </section>

      <section className="comparison-boundary" aria-labelledby="comparison-boundary-heading">
        <div>
          <p className="eyebrow">Claim boundary</p>
          <h2 id="comparison-boundary-heading">A diff is not a new validation run.</h2>
        </div>
        <p>{comparison.claim_boundary}</p>
      </section>

      <section className="comparison-results" aria-labelledby="comparison-results-heading">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Normalized persisted records</p>
            <h2 id="comparison-results-heading">Observed differences</h2>
          </div>
          <span>{comparison.returned_change_count} rows shown</span>
        </div>

        {comparison.summaries.length > 0 ? (
          <div className="comparison-summary-grid" aria-label="Change counts by evidence area">
            {comparison.summaries.map((summary) => (
              <article key={summary.area}>
                <strong>{readable(summary.area)}</strong>
                <span>
                  {summary.changed} changed · {summary.added} added · {summary.removed} removed
                </span>
              </article>
            ))}
          </div>
        ) : null}

        {comparison.changes.length === 0 ? (
          <div className="state-panel">
            No differences were observed in the normalized records within the stated limits.
            This does not prove geometric or physical equivalence.
          </div>
        ) : (
          <div className="comparison-change-list">
            {comparison.changes.map((change) => (
              <ChangeRow key={`${change.area}:${change.record_key}`} change={change} />
            ))}
          </div>
        )}
      </section>
    </>
  )
}
