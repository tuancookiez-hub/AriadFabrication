import modelSheetUrl from '../../assets/ariad-robot-interlocking-model-sheet-v3.png'

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
          alt="Ariad interlocking robot visual blueprint with front, side, rear, three-quarter, exploded, and tool-less interface detail views"
        />
      </div>
      <figcaption><strong>Visual blueprint</strong><span>Generated concept image · not generated CAD or fit evidence.</span></figcaption>
    </figure>
  )
}
