export interface Capabilities {
  read_only: boolean
  hardware_actions: boolean
}

export interface Source {
  kind: string
  label: string
  evidence_mode: string
  fixture: boolean
  physical_evidence_present: boolean
}

export interface RevisionSummary {
  job_id: string
  revision_id: string
  availability: 'available' | 'invalid'
  title: string | null
  job_status: string | null
  revision_number: number | null
  stage_count: number
  latest_stage: string | null
  latest_status: string | null
  achieved_evidence_level: string | null
  warning_count: number
  updated_at: string | null
  source: Source | null
  error: string | null
}

export interface RevisionListResponse {
  schema_version: string
  capabilities: Capabilities
  revisions: RevisionSummary[]
}

export interface EventRecord {
  event_id: string
  event_type: string
  status: string
  message: string
  sequence: number
  timestamp: string
  data: Record<string, unknown>
}

export interface Finding {
  finding_id: string
  code: string
  title: string
  severity: string
  evidence: string
  evidence_mode: string
  remediation: string | null
  affected_geometry: string | null
  resolved: boolean
  resolution: string | null
  data: Record<string, unknown>
}

export interface Artifact {
  artifact_id: string
  role: string
  media_type: string
  checksum_sha256: string
  size_bytes: number | null
  producer: string
  producer_version: string
  evidence_mode: string
  stage_run_id: string
  available: boolean
  download_url: string
  metadata: Record<string, unknown>
}

export interface Stage {
  stage_run_id: string
  stage: string
  status: string
  attempt: number
  evidence_mode: string
  evidence_level: string | null
  tool: { name: string; version: string }
  started_at: string | null
  completed_at: string | null
  summary: string
  error_message: string | null
  events: EventRecord[]
  findings: Finding[]
  artifacts: Artifact[]
  decisions: Record<string, unknown>[]
  approvals: Record<string, unknown>[]
}

export interface PackageSummary {
  status: string
  evidence_level: string | null
  allowed_claim: string | null
  claim_boundary: string | null
  hardware: {
    printer_selected: boolean
    printer_connected: boolean
    gcode_uploaded: boolean
    print_started: boolean
  }
  gcode_summary: {
    checksum_sha256: string | null
    slicer_version: string | null
    layer_count: number | null
    estimated_seconds: number | null
    filament_length_mm: number | null
    filament_mass_g: number | null
    motion_bounds_mm: Record<string, number> | null
    temperatures_c: Record<string, number[]> | null
    feature_counts: Record<string, number> | null
  } | null
  slicer: Record<string, unknown>
  unresolved_warning_count: number
}

export interface RevisionDetail {
  schema_version: string
  capabilities: Capabilities
  source: Source
  manifest_available: boolean
  job: {
    job_id: string
    title: string
    request: string
    status: string
    created_at: string
    updated_at: string
    metadata: Record<string, unknown>
  }
  revision: {
    revision_id: string
    number: number
    parent_revision_id: string | null
    reason: string
    created_at: string
    spec: Record<string, unknown>
  }
  stages: Stage[]
  package: PackageSummary | null
}
