import type {
  IntakeResponse,
  LocalCodexStatus,
  RevisionComparison,
  RevisionDetail,
  RevisionListResponse,
} from './types'

const apiRoot = (import.meta.env.VITE_ARIAD_API_ROOT ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
  }
}

async function requestJson<T>(
  path: string,
  signal?: AbortSignal,
  init: Pick<RequestInit, 'method' | 'body'> = {},
): Promise<T> {
  const response = await fetch(`${apiRoot}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
    },
    signal,
  })
  if (!response.ok) {
    let message = `Request failed with status ${response.status}`
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      // The status still provides a truthful fallback when the body is not JSON.
    }
    throw new ApiError(message, response.status)
  }
  return (await response.json()) as T
}

export function captureIdea(prompt: string, signal?: AbortSignal): Promise<IntakeResponse> {
  return requestJson('/api/v1/intake', signal, {
    method: 'POST',
    body: JSON.stringify({ prompt }),
  })
}

export function getLocalCodexStatus(signal?: AbortSignal): Promise<LocalCodexStatus> {
  return requestJson('/api/v1/codex/status', signal)
}

export function listRevisions(
  offset = 0,
  limit = 100,
  signal?: AbortSignal,
): Promise<RevisionListResponse> {
  const query = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
  })
  return requestJson(`/api/v1/revisions?${query}`, signal)
}

export function getRevision(
  jobId: string,
  revisionId: string,
  signal?: AbortSignal,
): Promise<RevisionDetail> {
  return requestJson(
    `/api/v1/revisions/${encodeURIComponent(jobId)}/${encodeURIComponent(revisionId)}`,
    signal,
  )
}

export function getRevisionComparison(
  baseJobId: string,
  baseRevisionId: string,
  candidateJobId: string,
  candidateRevisionId: string,
  signal?: AbortSignal,
): Promise<RevisionComparison> {
  const query = new URLSearchParams({
    base_job_id: baseJobId,
    base_revision_id: baseRevisionId,
    candidate_job_id: candidateJobId,
    candidate_revision_id: candidateRevisionId,
  })
  return requestJson(`/api/v1/revision-comparison?${query.toString()}`, signal)
}
