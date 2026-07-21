import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { getBrowserSession, listProjectIntents } from './api'
import type { ProjectIntent } from './types'

function isInternalRecord(project: ProjectIntent): boolean {
  return /^propose a design plan for ariad project\b/i.test(project.prompt.trim())
}

export function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectIntent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    getBrowserSession(controller.signal)
      .then((session) => listProjectIntents(session.session_token, controller.signal))
      .then((result) => setProjects(result.projects))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Projects could not load.')
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [])

  const sortedProjects = useMemo(
    () => [...projects].sort((left, right) => Date.parse(right.confirmed_at) - Date.parse(left.confirmed_at)),
    [projects],
  )
  const publicProjects = useMemo(() => sortedProjects.filter((project) => !isInternalRecord(project)), [sortedProjects])
  const distinctProjects = useMemo(() => {
    const prompts = new Set<string>()
    return publicProjects.filter((project) => {
      const key = project.prompt.trim().toLowerCase().replace(/\s+/g, ' ')
      if (prompts.has(key)) return false
      prompts.add(key)
      return true
    })
  }, [publicProjects])
  const visibleProjects = showAll ? sortedProjects : distinctProjects
  const hiddenCount = sortedProjects.length - distinctProjects.length

  return (
    <>
      <section className="projects-hero">
        <p className="eyebrow">Your workspace</p>
        <h1 data-route-heading tabIndex={-1}>My builds</h1>
        <p>Continue your latest distinct ideas. Rehearsal duplicates stay out of the way.</p>
      </section>
      <section className="projects-list" aria-busy={loading}>
        {loading ? <p role="status">Loading confirmed project intents...</p> : null}
        {error ? <div className="chat-error" role="alert">{error}</div> : null}
        {!loading && !error && projects.length === 0 ? (
          <div className="projects-empty"><h2>No saved projects yet</h2><p>Talk with Codex, then explicitly confirm an idea when it is worth preserving.</p><Link className="primary-action" to="/chat">Talk with Codex</Link></div>
        ) : null}
        {!loading && !error && hiddenCount > 0 ? <div className="project-list-controls"><span>{distinctProjects.length} distinct build{distinctProjects.length === 1 ? '' : 's'} · {hiddenCount} duplicate or internal record{hiddenCount === 1 ? '' : 's'} hidden</span><button className="text-action" type="button" onClick={() => setShowAll((current) => !current)}>{showAll ? 'Show clean list' : 'Show all records'}</button></div> : null}
        {visibleProjects.map((project) => (
          <article className="project-intent-card" key={project.project_id}>
            <div><span>Saved idea</span><time dateTime={project.confirmed_at}>{new Date(project.confirmed_at).toLocaleString()}</time></div>
            <h2>{project.title}</h2>
            <p>{project.prompt}</p>
            <footer><strong>Ready to continue</strong><span>Planning</span></footer>
            <Link className="secondary-action" to={`/projects/${project.project_id}`}>Open saved brief</Link>
          </article>
        ))}
      </section>
    </>
  )
}
