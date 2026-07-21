import type {
  IntakeResponse,
  BrowserSession,
  ConversationCancel,
  ConversationEvents,
  ConversationTurn,
  LocalCodexStatus,
  ProjectIntent,
  ProjectIntentList,
  ProjectDesignPlan,
  ProjectDesignPlanRequest,
  ProjectDesignProposal,
  ProjectDetail,
  ProjectDraft,
  ProjectDraftRequest,
  ProjectBrief,
  RevisionComparison,
  RevisionDetail,
  RevisionListResponse,
  AssemblySpec,
  LiveLBracket,
  LiveLBracketRequest,
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
  init: Pick<RequestInit, 'method' | 'body' | 'headers'> = {},
): Promise<T> {
  const response = await fetch(`${apiRoot}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...init.headers,
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

export function getRobotAssembly(signal?: AbortSignal): Promise<AssemblySpec> {
  return requestJson('/api/v1/assemblies/robot-concept', signal)
}

export function getBrowserSession(signal?: AbortSignal): Promise<BrowserSession> {
  return requestJson('/api/v1/session', signal)
}

export function startCodexTurn(
  prompt: string,
  sessionToken: string,
  signal?: AbortSignal,
): Promise<ConversationTurn> {
  return requestJson('/api/v1/codex/turns', signal, {
    method: 'POST',
    body: JSON.stringify({ prompt }),
    headers: { 'X-Ariad-Session': sessionToken },
  })
}

export function getCodexEvents(
  after: number,
  sessionToken: string,
  signal?: AbortSignal,
): Promise<ConversationEvents> {
  return requestJson(`/api/v1/codex/events?after=${after}`, signal, {
    headers: { 'X-Ariad-Session': sessionToken },
  })
}

export function cancelCodexTurn(
  sessionToken: string,
  signal?: AbortSignal,
): Promise<ConversationCancel> {
  return requestJson('/api/v1/codex/cancel', signal, {
    method: 'POST',
    headers: { 'X-Ariad-Session': sessionToken },
  })
}

export function createProjectIntent(
  title: string,
  prompt: string,
  sessionToken: string,
  signal?: AbortSignal,
): Promise<ProjectIntent> {
  return requestJson('/api/v1/projects', signal, {
    method: 'POST',
    body: JSON.stringify({ title, prompt, confirmed: true }),
    headers: { 'X-Ariad-Session': sessionToken },
  })
}

export function listProjectIntents(
  sessionToken: string,
  signal?: AbortSignal,
): Promise<ProjectIntentList> {
  return requestJson('/api/v1/projects?limit=100', signal, {
    headers: { 'X-Ariad-Session': sessionToken },
  })
}

export function getProjectDetail(projectId: string, sessionToken: string, signal?: AbortSignal): Promise<ProjectDetail> {
  return requestJson(`/api/v1/projects/${encodeURIComponent(projectId)}`, signal, {
    headers: { 'X-Ariad-Session': sessionToken },
  })
}

export function saveProjectDraft(projectId: string, draft: ProjectDraftRequest, sessionToken: string, signal?: AbortSignal): Promise<ProjectDraft> {
  return requestJson(`/api/v1/projects/${encodeURIComponent(projectId)}/draft`, signal, {
    method: 'PUT', body: JSON.stringify(draft), headers: { 'X-Ariad-Session': sessionToken },
  })
}

export function confirmProjectBrief(projectId: string, sessionToken: string, signal?: AbortSignal): Promise<ProjectBrief> {
  return requestJson(`/api/v1/projects/${encodeURIComponent(projectId)}/brief-confirmation`, signal, {
    method: 'POST', body: JSON.stringify({ confirmed: true }), headers: { 'X-Ariad-Session': sessionToken },
  })
}

export function saveProjectDesignPlan(projectId: string, plan: ProjectDesignPlanRequest, sessionToken: string, signal?: AbortSignal): Promise<ProjectDesignPlan> {
  return requestJson(`/api/v1/projects/${encodeURIComponent(projectId)}/design-plan`, signal, {
    method: 'PUT', body: JSON.stringify(plan), headers: { 'X-Ariad-Session': sessionToken },
  })
}

export function getProjectDesignProposal(projectId: string, sessionToken: string, signal?: AbortSignal): Promise<ProjectDesignProposal> {
  return requestJson(`/api/v1/projects/${encodeURIComponent(projectId)}/design-proposal`, signal, {
    headers: { 'X-Ariad-Session': sessionToken },
  })
}

export function generateLiveLBracket(
  request: LiveLBracketRequest,
  sessionToken: string,
  signal?: AbortSignal,
): Promise<LiveLBracket> {
  return requestJson('/api/v1/live-cad/l-bracket', signal, {
    method: 'POST',
    body: JSON.stringify(request),
    headers: { 'X-Ariad-Session': sessionToken },
  })
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
