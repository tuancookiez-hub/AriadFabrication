import { ModelInspector } from './ModelInspector'
import type { LiveLBracket } from './types'

type Mode = 'cad' | 'verify' | 'slice' | 'package'

function formatBytes(value: number): string {
  return value < 1024 * 1024 ? `${(value / 1024).toFixed(1)} KiB` : `${(value / (1024 * 1024)).toFixed(1)} MiB`
}

export function LiveBracketWorkspace({
  result,
  mode,
  onContinue,
  onAskCodex,
}: {
  result: LiveLBracket
  mode: Mode
  onContinue: () => void
  onAskCodex: (topic: string) => void
}) {
  const preview = result.artifacts.find((artifact) => artifact.role === 'browser_preview')
  const artifact = preview ? {
    download_url: preview.download_url,
    size_bytes: preview.size_bytes,
    checksum_sha256: preview.checksum_sha256,
  } : null
  const parameters = result.parameters
  const heading = mode === 'cad'
    ? 'This CAD was generated from your dimensions.'
    : mode === 'verify'
      ? 'The generated solid passed bounded digital checks.'
      : mode === 'slice'
        ? 'Choose a printer profile before slicing.'
        : 'Download the live digital CAD package.'

  return <section className="cad-workspace live-cad-workspace" aria-labelledby="live-cad-title">
    <header className="cad-workspace-heading">
      <div><p className="eyebrow">Live bounded generation</p><h2 id="live-cad-title">{heading}</h2><p>This is not a replayed fixture. Ariad executed its registered L-bracket family for the confirmed parameters below.</p></div>
      <span className="cad-status"><i /> {result.cache_reused ? 'Deterministic result reused' : 'Generated in this session'}</span>
    </header>
    <div className="live-cad-proof">
      <span><strong>Generation</strong>{result.generation_id}</span>
      <span><strong>Parameter hash</strong>{result.parameter_sha256.slice(0, 16)}…</span>
      <span><strong>Kernel</strong>{result.checks.kernel_valid && result.checks.solid_count === 1 ? 'Valid single solid' : 'Review required'}</span>
    </div>
    <div className="cad-workspace-layout">
      <aside className="live-parameter-list" aria-label="Generated CAD parameters">
        <h3>Confirmed parameters</h3>
        <dl>
          <div><dt>Width</dt><dd>{parameters.width_mm} mm</dd></div>
          <div><dt>Base depth</dt><dd>{parameters.base_depth_mm} mm</dd></div>
          <div><dt>Upright height</dt><dd>{parameters.upright_height_mm} mm</dd></div>
          <div><dt>Thickness</dt><dd>{parameters.thickness_mm} mm</dd></div>
          <div><dt>Hole diameter</dt><dd>{parameters.hole_diameter_mm} mm</dd></div>
          <div><dt>Hole spacing</dt><dd>{parameters.hole_spacing_mm} mm</dd></div>
          <div><dt>Edge margin</dt><dd>{parameters.edge_margin_mm} mm</dd></div>
        </dl>
      </aside>
      <div className="cad-part-preview">
        <ModelInspector artifact={artifact} />
        <div className="live-cad-artifacts">
          {result.artifacts.map((item) => <a href={item.download_url} download key={item.role}><strong>{item.role.replaceAll('_', ' ')}</strong><span>{formatBytes(item.size_bytes)} · {item.checksum_sha256.slice(0, 10)}…</span></a>)}
        </div>
      </div>
    </div>
    {mode === 'verify' ? <div className="live-check-grid">
      <span><b>✓</b> Kernel-valid</span><span><b>✓</b> One solid</span><span><b>✓</b> {result.checks.bounds_mm.x} × {result.checks.bounds_mm.y} × {result.checks.bounds_mm.z} mm</span><span><b>✓</b> {result.checks.preview_triangle_count.toLocaleString()} preview triangles</span>
    </div> : null}
    {mode === 'slice' ? <div className="live-cad-boundary"><strong>No slicer claim for this live family yet</strong><p>The generated STEP and STL are real. A printer, material, process, and orientation profile have not been approved for this parameter set, so Ariad does not display invented G-code.</p></div> : null}
    {mode === 'package' ? <div className="live-cad-boundary"><strong>Digital geometry handoff ready</strong><p>{result.claim_boundary}</p></div> : null}
    <div className="cad-next-step"><div><strong>{mode === 'package' ? 'Live generation complete' : 'Continue with the evidence visible'}</strong><p>Change the dimensions in a new build to produce a different parameter hash and model.</p></div><div className="cad-next-actions"><button className="secondary-action" type="button" onClick={() => onAskCodex('Help me review this live generated L-bracket and its remaining printability questions.')}>Ask Codex</button>{mode !== 'package' ? <button className="primary-action" type="button" onClick={onContinue}>{mode === 'cad' ? 'Verify geometry →' : mode === 'verify' ? 'Review slicing boundary →' : 'Build digital package →'}</button> : null}</div></div>
  </section>
}
