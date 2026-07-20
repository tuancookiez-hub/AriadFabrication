import { useState } from 'react'

import type {
  Artifact,
  Finding,
  Inspection,
  InspectionCheck,
  InspectionFeature,
  InspectionProfile,
  InspectionReport,
} from './types'

type EvidenceScope = 'features' | 'reports' | 'findings' | 'profiles' | 'artifacts'

function readable(value: string): string {
  return value.replaceAll('_', ' ')
}

function valueText(value: unknown): string {
  if (value === null || value === undefined) return 'Not recorded'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value, null, 2)
}

function ValueBlock({ value }: { value: unknown }) {
  const text = valueText(value)
  const structured = typeof value === 'object' && value !== null
  return structured ? <pre className="evidence-value">{text}</pre> : <span>{text}</span>
}

function ReportSource({ report }: { report: InspectionReport }) {
  return (
    <dl className="evidence-source">
      <div>
        <dt>Persisted source</dt>
        <dd>{readable(report.artifact.role)}</dd>
      </div>
      <div>
        <dt>Evidence mode</dt>
        <dd>{report.artifact.evidence_mode}</dd>
      </div>
      <div>
        <dt>Checksum verification</dt>
        <dd>{report.artifact.checksum_verified ? 'Verified before parsing' : 'Unavailable'}</dd>
      </div>
      <div>
        <dt>SHA-256</dt>
        <dd>
          <code>{report.artifact.checksum_sha256}</code>
        </dd>
      </div>
    </dl>
  )
}

function CheckDetail({ check }: { check: InspectionCheck }) {
  return (
    <article className="selected-evidence" aria-live="polite">
      <div className="selected-evidence-heading">
        <div>
          <p className="eyebrow">Selected persisted check</p>
          <h4>{readable(check.check_id)}</h4>
        </div>
        <span className={`check-result check-result-${check.passed ? 'pass' : 'fail'}`}>
          {check.passed ? 'Passed' : 'Failed'}
        </span>
      </div>
      <p>{check.description}</p>
      <dl className="check-comparison">
        <div>
          <dt>Recorded result</dt>
          <dd>
            <ValueBlock value={check.actual} />
          </dd>
        </div>
        <div>
          <dt>Recorded requirement</dt>
          <dd>
            <ValueBlock value={check.requirement} />
          </dd>
        </div>
        {check.tolerance_mm !== null ? (
          <div>
            <dt>Tolerance</dt>
            <dd>{check.tolerance_mm} mm</dd>
          </div>
        ) : null}
        {check.category ? (
          <div>
            <dt>Category</dt>
            <dd>{readable(check.category)}</dd>
          </div>
        ) : null}
      </dl>
      {check.remediation ? <p className="next-evidence">If failed: {check.remediation}</p> : null}
    </article>
  )
}

function ReportExplorer({ reports }: { reports: InspectionReport[] }) {
  const [reportKind, setReportKind] = useState(reports[0]?.report_kind ?? '')
  const selectedReport = reports.find((item) => item.report_kind === reportKind) ?? reports[0]
  const [checkId, setCheckId] = useState(selectedReport?.checks[0]?.check_id ?? '')
  const selectedCheck =
    selectedReport?.checks.find((item) => item.check_id === checkId) ?? selectedReport?.checks[0]

  if (!selectedReport) {
    return <div className="evidence-empty">No checksum-verified report is available.</div>
  }

  const selectReport = (report: InspectionReport): void => {
    setReportKind(report.report_kind)
    setCheckId(report.checks[0]?.check_id ?? '')
  }

  return (
    <div className="report-explorer">
      <div className="evidence-choice-list" role="group" aria-label="Persisted reports">
        {reports.map((report) => (
          <button
            type="button"
            aria-pressed={selectedReport.report_kind === report.report_kind}
            key={report.report_kind}
            onClick={() => selectReport(report)}
          >
            <strong>{report.title}</strong>
            <span>
              {report.checks.length} checks ·{' '}
              {report.status ??
                (report.passed === null
                  ? 'status unavailable'
                  : report.passed
                    ? 'passed'
                    : 'failed')}
            </span>
          </button>
        ))}
      </div>

      <div className="report-summary">
        <div>
          <p className="eyebrow">Checksum-verified report</p>
          <h3>{selectedReport.title}</h3>
        </div>
        <span
          className={`check-result check-result-${
            selectedReport.passed === null
              ? 'recorded'
              : selectedReport.passed
                ? 'pass'
                : 'fail'
          }`}
        >
          {selectedReport.passed === null
            ? 'Recorded'
            : selectedReport.passed
              ? 'Passed'
              : 'Failed'}
        </span>
      </div>
      {selectedReport.claim_boundary ? (
        <p className="report-claim-boundary">{selectedReport.claim_boundary}</p>
      ) : null}
      <ReportSource report={selectedReport} />

      <div className="check-browser">
        <div className="check-list" role="group" aria-label={`${selectedReport.title} checks`}>
          {selectedReport.checks.map((check) => (
            <button
              type="button"
              aria-label={`${readable(check.check_id)} — ${check.passed ? 'passed' : 'failed'}`}
              aria-pressed={selectedCheck?.check_id === check.check_id}
              key={check.check_id}
              onClick={() => setCheckId(check.check_id)}
            >
              <span className={`check-dot check-dot-${check.passed ? 'pass' : 'fail'}`} aria-hidden="true" />
              <span>{readable(check.check_id)}</span>
              <span className="check-list-result">{check.passed ? 'Pass' : 'Fail'}</span>
            </button>
          ))}
        </div>
        {selectedCheck ? <CheckDetail check={selectedCheck} /> : null}
      </div>

      {selectedReport.messages.length > 0 ? (
        <div className="inspection-messages">
          <h4>Recorded warnings and errors</h4>
          {selectedReport.messages.map((message, index) => (
            <article className={`inspection-message inspection-message-${message.severity}`} key={`${message.code ?? message.title}-${index}`}>
              <strong>{message.title}</strong>
              <p>{message.message}</p>
              {message.remediation ? <small>Next evidence: {message.remediation}</small> : null}
            </article>
          ))}
        </div>
      ) : null}

      {Object.keys(selectedReport.measurements).length > 0 ? (
        <details className="measurement-records">
          <summary>{Object.keys(selectedReport.measurements).length} recorded measurements</summary>
          <dl>
            {Object.entries(selectedReport.measurements).map(([name, value]) => (
              <div key={name}>
                <dt>{readable(name)}</dt>
                <dd>
                  <ValueBlock value={value} />
                </dd>
              </div>
            ))}
          </dl>
        </details>
      ) : null}
    </div>
  )
}

function FeatureExplorer({ features }: { features: InspectionFeature[] }) {
  const [featureId, setFeatureId] = useState(features[0]?.feature_id ?? '')
  const feature = features.find((item) => item.feature_id === featureId) ?? features[0]
  if (!feature) {
    return <div className="evidence-empty">No bounded feature requirement is available.</div>
  }
  return (
    <div className="record-explorer">
      <div className="evidence-choice-list" role="group" aria-label="Persisted feature requirements">
        {features.map((item) => (
          <button
            type="button"
            aria-pressed={feature.feature_id === item.feature_id}
            key={item.feature_id}
            onClick={() => setFeatureId(item.feature_id)}
          >
            <strong>{readable(item.feature_id)}</strong>
            <span>{readable(item.kind)} · quantity {item.quantity}</span>
          </button>
        ))}
      </div>
      <article className="selected-evidence" aria-live="polite">
        <p className="eyebrow">Selected persisted requirement</p>
        <h3>{readable(feature.feature_id)}</h3>
        <p>
          This is a requested feature from the revision specification, not a measured result or a
          spatial highlight.
        </p>
        <dl className="profile-values">
          <div>
            <dt>Kind</dt>
            <dd>{readable(feature.kind)}</dd>
          </div>
          <div>
            <dt>Quantity</dt>
            <dd>{feature.quantity}</dd>
          </div>
          <div>
            <dt>Required</dt>
            <dd>{feature.required ? 'Yes' : 'No'}</dd>
          </div>
          <div>
            <dt>Tolerance</dt>
            <dd>{feature.tolerance_mm === null ? 'Not recorded' : `${feature.tolerance_mm} mm`}</dd>
          </div>
          {Object.entries(feature.dimensions_mm).map(([name, value]) => (
            <div key={name}>
              <dt>{readable(name)}</dt>
              <dd>{value} mm</dd>
            </div>
          ))}
          <div>
            <dt>Source</dt>
            <dd>
              Persisted revision specification{feature.fixture ? ' · interface fixture' : ''}
            </dd>
          </div>
        </dl>
        {feature.notes ? <p>{feature.notes}</p> : null}
      </article>
    </div>
  )
}

function FindingExplorer({ findings }: { findings: Finding[] }) {
  const [findingId, setFindingId] = useState(findings[0]?.finding_id ?? '')
  const finding = findings.find((item) => item.finding_id === findingId) ?? findings[0]
  if (!finding) return <div className="evidence-empty">No finding is recorded in this revision.</div>
  return (
    <div className="record-explorer">
      <div className="evidence-choice-list" role="group" aria-label="Persisted findings">
        {findings.map((item) => (
          <button
            type="button"
            aria-pressed={finding.finding_id === item.finding_id}
            key={item.finding_id}
            onClick={() => setFindingId(item.finding_id)}
          >
            <strong>{item.title}</strong>
            <span>{item.severity} · {item.resolved ? 'resolved' : 'unresolved'}</span>
          </button>
        ))}
      </div>
      <article className={`selected-evidence finding-${finding.severity}`} aria-live="polite">
        <p className="eyebrow">Selected persisted finding</p>
        <h3>{finding.title}</h3>
        <p>{finding.evidence}</p>
        <dl className="check-comparison">
          <div>
            <dt>Code</dt>
            <dd>{finding.code}</dd>
          </div>
          <div>
            <dt>Evidence mode</dt>
            <dd>{finding.evidence_mode}</dd>
          </div>
          <div>
            <dt>Affected geometry</dt>
            <dd>{finding.affected_geometry ?? 'Not spatially mapped'}</dd>
          </div>
        </dl>
        {finding.remediation ? <p className="next-evidence">Next evidence: {finding.remediation}</p> : null}
      </article>
    </div>
  )
}

function ProfileExplorer({ profiles }: { profiles: InspectionProfile[] }) {
  const profileKey = (item: InspectionProfile): string => `${item.profile_kind}:${item.profile_id}`
  const [selectedKey, setSelectedKey] = useState(profiles[0] ? profileKey(profiles[0]) : '')
  const profile = profiles.find((item) => profileKey(item) === selectedKey) ?? profiles[0]
  if (!profile) return <div className="evidence-empty">No checksum-verified profile is available.</div>
  return (
    <div className="record-explorer">
      <div className="evidence-choice-list" role="group" aria-label="Persisted profiles">
        {profiles.map((item) => (
          <button
            type="button"
            aria-pressed={profileKey(profile) === profileKey(item)}
            key={`${item.profile_kind}-${item.profile_id}`}
            onClick={() => setSelectedKey(profileKey(item))}
          >
            <strong>{readable(item.profile_kind)}</strong>
            <span>{item.profile_id}</span>
          </button>
        ))}
      </div>
      <article className="selected-evidence" aria-live="polite">
        <p className="eyebrow">Selected persisted profile</p>
        <h3>{profile.name}</h3>
        <p>{profile.claim_boundary ?? 'No profile claim boundary was recorded.'}</p>
        <dl className="profile-values">
          <div>
            <dt>Status</dt>
            <dd>{readable(profile.status)}</dd>
          </div>
          {Object.entries(profile.values).map(([name, value]) => (
            <div key={name}>
              <dt>{readable(name)}</dt>
              <dd>
                <ValueBlock value={value} />
              </dd>
            </div>
          ))}
        </dl>
        <div className="checksum-record">
          <span>Verified source SHA-256</span>
          <code>{profile.artifact.checksum_sha256}</code>
        </div>
      </article>
    </div>
  )
}

function ArtifactExplorer({ artifacts }: { artifacts: Artifact[] }) {
  const [artifactId, setArtifactId] = useState(artifacts[0]?.artifact_id ?? '')
  const artifact = artifacts.find((item) => item.artifact_id === artifactId) ?? artifacts[0]
  if (!artifact) return <div className="evidence-empty">No artifact is recorded in this revision.</div>
  return (
    <div className="record-explorer">
      <div className="evidence-choice-list artifact-choice-list" role="group" aria-label="Persisted artifacts">
        {artifacts.map((item) => (
          <button
            type="button"
            aria-pressed={artifact.artifact_id === item.artifact_id}
            key={item.artifact_id}
            onClick={() => setArtifactId(item.artifact_id)}
          >
            <strong>{readable(item.role)}</strong>
            <span>{item.available ? 'recorded file available' : 'recorded file unavailable'}</span>
          </button>
        ))}
      </div>
      <article className="selected-evidence" aria-live="polite">
        <p className="eyebrow">Selected persisted artifact</p>
        <h3>{readable(artifact.role)}</h3>
        <dl className="profile-values">
          <div>
            <dt>Artifact ID</dt>
            <dd>{artifact.artifact_id}</dd>
          </div>
          <div>
            <dt>Producer</dt>
            <dd>{artifact.producer} {artifact.producer_version}</dd>
          </div>
          <div>
            <dt>Media type</dt>
            <dd>{artifact.media_type}</dd>
          </div>
          <div>
            <dt>Evidence mode</dt>
            <dd>{artifact.evidence_mode}</dd>
          </div>
          <div>
            <dt>Recorded size</dt>
            <dd>{artifact.size_bytes === null ? 'Not recorded' : `${artifact.size_bytes.toLocaleString()} bytes`}</dd>
          </div>
          <div>
            <dt>Metadata</dt>
            <dd>
              <ValueBlock value={artifact.metadata} />
            </dd>
          </div>
        </dl>
        <div className="checksum-record">
          <span>Recorded SHA-256 · verified again when opened</span>
          <code>{artifact.checksum_sha256}</code>
        </div>
        {artifact.available ? (
          <a className="evidence-open-link" href={artifact.download_url}>Open checksum-verified artifact</a>
        ) : (
          <p className="artifact-unavailable">The recorded file is unavailable or its size differs.</p>
        )}
      </article>
    </div>
  )
}

export function EvidenceInspector({
  inspection,
  findings,
  artifacts,
}: {
  inspection: Inspection
  findings: Finding[]
  artifacts: Artifact[]
}) {
  const initialScope: EvidenceScope = inspection.reports.length
    ? 'reports'
    : inspection.features.length
      ? 'features'
    : findings.length
      ? 'findings'
      : inspection.profiles.length
        ? 'profiles'
        : 'artifacts'
  const [scope, setScope] = useState<EvidenceScope>(initialScope)

  return (
    <div className="evidence-inspector">
      <div className="evidence-boundary">
        <strong>Persisted evidence replay</strong>
        <p>{inspection.claim_boundary}</p>
        <p>Selection changes only the explanation. It does not highlight exact geometry or rerun a check.</p>
      </div>
      <div className="evidence-scope-tabs" role="group" aria-label="Evidence record type">
        <button type="button" aria-pressed={scope === 'features'} onClick={() => setScope('features')}>
          Features <span>{inspection.features.length}</span>
        </button>
        <button type="button" aria-pressed={scope === 'reports'} onClick={() => setScope('reports')}>
          Reports <span>{inspection.reports.length}</span>
        </button>
        <button type="button" aria-pressed={scope === 'findings'} onClick={() => setScope('findings')}>
          Findings <span>{findings.length}</span>
        </button>
        <button type="button" aria-pressed={scope === 'profiles'} onClick={() => setScope('profiles')}>
          Profiles <span>{inspection.profiles.length}</span>
        </button>
        <button type="button" aria-pressed={scope === 'artifacts'} onClick={() => setScope('artifacts')}>
          Artifacts <span>{artifacts.length}</span>
        </button>
      </div>

      {scope === 'features' ? <FeatureExplorer features={inspection.features} /> : null}
      {scope === 'reports' ? <ReportExplorer reports={inspection.reports} /> : null}
      {scope === 'findings' ? <FindingExplorer findings={findings} /> : null}
      {scope === 'profiles' ? <ProfileExplorer profiles={inspection.profiles} /> : null}
      {scope === 'artifacts' ? <ArtifactExplorer artifacts={artifacts} /> : null}

      {inspection.unavailable.length > 0 ? (
        <div className="inspection-unavailable" role="status">
          <h4>Inspection sources unavailable</h4>
          {inspection.unavailable.map((item) => (
            <p key={`${item.role}-${item.reason}`}>
              <strong>{readable(item.role)}:</strong> {item.message} ({readable(item.reason)})
            </p>
          ))}
        </div>
      ) : null}
    </div>
  )
}
