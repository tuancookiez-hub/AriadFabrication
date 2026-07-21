import modelSheetUrl from '../../assets/ariad-robot-component-first-model-sheet-v4.png'

type AssemblyBlueprintProps = {
  compact?: boolean
}

export function AssemblyBlueprint({ compact = false }: AssemblyBlueprintProps) {
  return (
    <figure className={`assembly-blueprint model-sheet-preview${compact ? ' assembly-blueprint-compact' : ''}`}>
      <div className="blueprint-toolbar">
        <span><i /> Concept model sheet</span>
        <span>5 views · 9 interlocking parts</span>
      </div>
      <div className="model-sheet-image-wrap">
        <img
          src={modelSheetUrl}
          alt="Ariad component-first robot blueprint with assembled, rear service, internal hardware, exploded assembly, and flat-print part views"
        />
      </div>
      <figcaption><strong>Component-first blueprint</strong><span>Pi and servo architecture precedes the shell · visual intent, not physical fit evidence.</span></figcaption>
    </figure>
  )
}
