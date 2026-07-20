type AssemblyBlueprintProps = {
  compact?: boolean
}

const parts = [
  { id: '01', name: 'Front shell', className: 'blueprint-shell-front' },
  { id: '02', name: 'Electronics tray', className: 'blueprint-tray' },
  { id: '03', name: 'Rear service panel', className: 'blueprint-shell-rear' },
  { id: '04', name: 'Left side limb', className: 'blueprint-limb-left' },
  { id: '05', name: 'Right side limb', className: 'blueprint-limb-right' },
]

export function AssemblyBlueprint({ compact = false }: AssemblyBlueprintProps) {
  return (
    <figure className={`assembly-blueprint${compact ? ' assembly-blueprint-compact' : ''}`}>
      <div className="blueprint-toolbar">
        <span><i /> Assembly plan</span>
        <span>9 parts · 7 interfaces</span>
      </div>
      <div className="blueprint-canvas" role="img" aria-label="Exploded planning diagram of a two-servo robot assembly">
        <div className="blueprint-grid" aria-hidden="true" />
        <div className="blueprint-axis" aria-hidden="true"><span>X</span><span>Y</span><span>Z</span></div>
        <div className="blueprint-measure blueprint-measure-width" aria-hidden="true"><span>110 mm envelope</span></div>
        <div className="blueprint-robot" aria-hidden="true">
          {parts.map((part) => <div className={`blueprint-part ${part.className}`} key={part.id}><b>{part.id}</b><span>{part.name}</span></div>)}
          <div className="blueprint-servo blueprint-servo-left"><b>S1</b></div>
          <div className="blueprint-servo blueprint-servo-right"><b>S2</b></div>
          <div className="blueprint-camera"><span /></div>
          <i className="explode-line explode-line-a" />
          <i className="explode-line explode-line-b" />
        </div>
        <div className="model-sheet-views" aria-hidden="true">
          <div className="model-sheet-view"><span className="mini-robot mini-front"><i /></span><b>Front</b></div>
          <div className="model-sheet-view"><span className="mini-robot mini-side"><i /></span><b>Side</b></div>
          <div className="model-sheet-view"><span className="mini-robot mini-rear"><i /></span><b>Rear</b></div>
        </div>
      </div>
      <figcaption><strong>Concept model sheet</strong><span>Multi-view planning reference · not generated CAD.</span></figcaption>
    </figure>
  )
}
