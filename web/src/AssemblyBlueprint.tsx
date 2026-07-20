import modelSheetUrl from '../../assets/ariad-robot-model-sheet-v2.png'

type AssemblyBlueprintProps = {
  compact?: boolean
}

export function AssemblyBlueprint({ compact = false }: AssemblyBlueprintProps) {
  return (
    <figure className={`assembly-blueprint model-sheet-preview${compact ? ' assembly-blueprint-compact' : ''}`}>
      <div className="blueprint-toolbar">
        <span><i /> Concept model sheet</span>
        <span>5 views · 9 callouts</span>
      </div>
      <div className="model-sheet-image-wrap">
        <img
          src={modelSheetUrl}
          alt="Ariad robot concept model sheet with front, side, rear, three-quarter, and exploded assembly views"
        />
      </div>
      <figcaption><strong>Planning reference</strong><span>Generated concept sheet · not generated CAD.</span></figcaption>
    </figure>
  )
}
