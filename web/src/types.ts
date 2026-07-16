import type { components } from './generated/interface-api'

type ApiSchemas = components['schemas']

export type Capabilities = ApiSchemas['CapabilitiesView']
export type Source = ApiSchemas['SourceView']
export type RevisionSummary = ApiSchemas['RevisionSummary']
export type RevisionListResponse = ApiSchemas['RevisionListResponse']
export type EventRecord = ApiSchemas['EventView']
export type Finding = ApiSchemas['FindingView']
export type Artifact = ApiSchemas['ArtifactView']
export type Stage = ApiSchemas['StageView']
export type PackageSummary = ApiSchemas['PackageView']
export type RevisionDetail = ApiSchemas['RevisionDetailResponse']
