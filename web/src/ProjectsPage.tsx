import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { getBrowserSession, listProjectIntents } from './api'
import type { ProjectIntent } from './types'

export function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectIntent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

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

  return (
    <>
      <section className="projects-hero">
        <p className="eyebrow">Confirmed intent library</p>
        <h1 data-route-heading tabIndex={-1}>Projects begin with a promise, not a print.</h1>
        <p>Each record below was explicitly saved by you. It still needs clarification before it can become an R0 Brief.</p>
      </section>
      <section className="projects-list" aria-busy={loading}>
        {loading ? <p role="status">Loading confirmed project intents...</p> : null}
        {error ? <div className="chat-error" role="alert">{error}</div> : null}
        {!loading && !error && projects.length === 0 ? (
          <div className="projects-empty"><h2>No saved projects yet</h2><p>Talk with Codex, then explicitly confirm an idea when it is worth preserving.</p><Link className="primary-action" to="/chat">Talk with Codex</Link></div>
        ) : null}
        {projects.map((project) => (
          <article className="project-intent-card" key={project.project_id}>
            <div><span>Intent confirmed</span><time dateTime={project.confirmed_at}>{new Date(project.confirmed_at).toLocaleString()}</time></div>
            <h2>{project.title}</h2>
            <p>{project.prompt}</p>
            <footer><strong>Brief evidence: none</strong><span>Fabrication not started</span></footer>
          </article>
        ))}
      </section>
    </>
  )
}
