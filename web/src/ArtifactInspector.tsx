import { type KeyboardEvent, useRef, useState } from 'react'

import { EvidenceInspector } from './EvidenceInspector'
import { ModelInspector } from './ModelInspector'
import { ToolpathInspector } from './ToolpathInspector'
import type { Artifact, Finding, Inspection } from './types'

type InspectionMode = 'model' | 'evidence' | 'toolpath'
const inspectionModes: InspectionMode[] = ['model', 'evidence', 'toolpath']

export function ArtifactInspector({
  previewArtifact,
  gcodeArtifact,
  inspection,
  findings,
  artifacts,
}: {
  previewArtifact: Artifact | null
  gcodeArtifact: Artifact | null
  inspection: Inspection
  findings: Finding[]
  artifacts: Artifact[]
}) {
  const initialMode: InspectionMode = previewArtifact
    ? 'model'
    : gcodeArtifact
      ? 'toolpath'
      : 'evidence'
  const [mode, setMode] = useState<InspectionMode>(initialMode)
  const [visitedModes, setVisitedModes] = useState<Set<InspectionMode>>(
    () => new Set([initialMode]),
  )
  const tabRefs = useRef<Record<InspectionMode, HTMLButtonElement | null>>({
    model: null,
    evidence: null,
    toolpath: null,
  })
  const selectMode = (nextMode: InspectionMode): void => {
    setMode(nextMode)
    setVisitedModes((current) => {
      if (current.has(nextMode)) return current
      return new Set([...current, nextMode])
    })
  }
  const moveTabFocus = (
    event: KeyboardEvent<HTMLButtonElement>,
    currentMode: InspectionMode,
  ): void => {
    const currentIndex = inspectionModes.indexOf(currentMode)
    let nextIndex: number | null = null
    if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % inspectionModes.length
    if (event.key === 'ArrowLeft') {
      nextIndex = (currentIndex - 1 + inspectionModes.length) % inspectionModes.length
    }
    if (event.key === 'Home') nextIndex = 0
    if (event.key === 'End') nextIndex = inspectionModes.length - 1
    if (nextIndex === null) return
    event.preventDefault()
    const nextMode = inspectionModes[nextIndex]
    selectMode(nextMode)
    tabRefs.current[nextMode]?.focus()
  }

  return (
    <div className="artifact-inspector">
      <div className="inspector-tabs" role="tablist" aria-label="Artifact inspection mode">
        <button
          type="button"
          id="model-inspection-tab"
          role="tab"
          aria-controls="model-inspection-panel"
          aria-selected={mode === 'model'}
          onClick={() => selectMode('model')}
          onKeyDown={(event) => moveTabFocus(event, 'model')}
          ref={(element) => { tabRefs.current.model = element }}
          tabIndex={mode === 'model' ? 0 : -1}
        >
          Model
        </button>
        <button
          type="button"
          id="evidence-inspection-tab"
          role="tab"
          aria-controls="evidence-inspection-panel"
          aria-selected={mode === 'evidence'}
          onClick={() => selectMode('evidence')}
          onKeyDown={(event) => moveTabFocus(event, 'evidence')}
          ref={(element) => { tabRefs.current.evidence = element }}
          tabIndex={mode === 'evidence' ? 0 : -1}
        >
          Evidence
        </button>
        <button
          type="button"
          id="toolpath-inspection-tab"
          role="tab"
          aria-controls="toolpath-inspection-panel"
          aria-selected={mode === 'toolpath'}
          onClick={() => selectMode('toolpath')}
          onKeyDown={(event) => moveTabFocus(event, 'toolpath')}
          ref={(element) => { tabRefs.current.toolpath = element }}
          tabIndex={mode === 'toolpath' ? 0 : -1}
        >
          Toolpath
        </button>
      </div>
      {visitedModes.has('model') ? (
        <div
          id="model-inspection-panel"
          role="tabpanel"
          aria-labelledby="model-inspection-tab"
          hidden={mode !== 'model'}
          tabIndex={0}
        >
          <ModelInspector
            artifact={previewArtifact}
            key={previewArtifact?.artifact_id ?? 'no-preview'}
          />
        </div>
      ) : null}
      {visitedModes.has('evidence') ? (
        <div
          id="evidence-inspection-panel"
          role="tabpanel"
          aria-labelledby="evidence-inspection-tab"
          hidden={mode !== 'evidence'}
          tabIndex={0}
        >
          <EvidenceInspector artifacts={artifacts} findings={findings} inspection={inspection} />
        </div>
      ) : null}
      {visitedModes.has('toolpath') ? (
        <div
          id="toolpath-inspection-panel"
          role="tabpanel"
          aria-labelledby="toolpath-inspection-tab"
          hidden={mode !== 'toolpath'}
          tabIndex={0}
        >
          <ToolpathInspector
            active={mode === 'toolpath'}
            artifact={gcodeArtifact}
            key={gcodeArtifact?.artifact_id ?? 'no-gcode'}
          />
        </div>
      ) : null}
    </div>
  )
}
