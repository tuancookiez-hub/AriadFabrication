import { useState } from 'react'

import { ModelInspector } from './ModelInspector'
import { ToolpathInspector } from './ToolpathInspector'
import type { Artifact } from './types'

type InspectionMode = 'model' | 'toolpath'

export function ArtifactInspector({
  previewArtifact,
  gcodeArtifact,
}: {
  previewArtifact: Artifact | null
  gcodeArtifact: Artifact | null
}) {
  const initialMode: InspectionMode = previewArtifact ? 'model' : gcodeArtifact ? 'toolpath' : 'model'
  const [mode, setMode] = useState<InspectionMode>(initialMode)
  const [visitedModes, setVisitedModes] = useState<Set<InspectionMode>>(
    () => new Set([initialMode]),
  )
  const selectMode = (nextMode: InspectionMode): void => {
    setMode(nextMode)
    setVisitedModes((current) => {
      if (current.has(nextMode)) return current
      return new Set([...current, nextMode])
    })
  }

  return (
    <div className="artifact-inspector">
      <div className="inspector-tabs" role="group" aria-label="Artifact inspection mode">
        <button
          type="button"
          aria-pressed={mode === 'model'}
          onClick={() => selectMode('model')}
        >
          Model
        </button>
        <button
          type="button"
          aria-pressed={mode === 'toolpath'}
          onClick={() => selectMode('toolpath')}
        >
          Toolpath
        </button>
      </div>
      {visitedModes.has('model') ? (
        <div id="model-inspection-panel" hidden={mode !== 'model'}>
          <ModelInspector artifact={previewArtifact} key={previewArtifact?.artifact_id ?? 'no-preview'} />
        </div>
      ) : null}
      {visitedModes.has('toolpath') ? (
        <div id="toolpath-inspection-panel" hidden={mode !== 'toolpath'}>
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
