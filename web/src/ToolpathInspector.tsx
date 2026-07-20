import { useEffect, useRef, useState } from 'react'

import {
  TOOLPATH_RECORD_SIZE,
  type ToolpathBounds,
  type ToolpathSummary,
} from './toolpath'
import type { Artifact } from './types'

interface LayerPayload {
  layerIndex: number
  zMm: number
  bounds: ToolpathBounds
  extrusionSegmentCount: number
  travelSegmentCount: number
  sourceSegmentCount: number
  returnedSegmentCount: number
  truncated: boolean
  segments: Float32Array
}

type WorkerResponse =
  | { type: 'ready'; summary: ToolpathSummary }
  | ({ type: 'layer' } & LayerPayload)
  | { type: 'error'; message: string }

function drawLayer(canvas: HTMLCanvasElement, layer: LayerPayload): void {
  const context = canvas.getContext('2d')
  if (!context) return
  const width = Math.max(canvas.parentElement?.clientWidth ?? 320, 320)
  const height = 320
  const pixelRatio = Math.min(window.devicePixelRatio || 1, 2)
  canvas.width = Math.round(width * pixelRatio)
  canvas.height = Math.round(height * pixelRatio)
  canvas.style.width = `${width}px`
  canvas.style.height = `${height}px`
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0)
  context.fillStyle = '#0d0d0f'
  context.fillRect(0, 0, width, height)

  const padding = 28
  const spanX = Math.max(layer.bounds.maxX - layer.bounds.minX, 1)
  const spanY = Math.max(layer.bounds.maxY - layer.bounds.minY, 1)
  const scale = Math.min((width - padding * 2) / spanX, (height - padding * 2) / spanY)
  const contentWidth = spanX * scale
  const contentHeight = spanY * scale
  const offsetX = (width - contentWidth) / 2 - layer.bounds.minX * scale
  const offsetY = (height - contentHeight) / 2 + layer.bounds.maxY * scale

  context.strokeStyle = '#242429'
  context.lineWidth = 1
  for (let index = 0; index <= 8; index += 1) {
    const x = padding + ((width - padding * 2) * index) / 8
    const y = padding + ((height - padding * 2) * index) / 8
    context.beginPath()
    context.moveTo(x, padding)
    context.lineTo(x, height - padding)
    context.moveTo(padding, y)
    context.lineTo(width - padding, y)
    context.stroke()
  }

  const renderKind = (extruding: boolean): void => {
    context.beginPath()
    for (let offset = 0; offset < layer.segments.length; offset += TOOLPATH_RECORD_SIZE) {
      if (Boolean(layer.segments[offset + 4]) !== extruding) continue
      context.moveTo(
        offsetX + layer.segments[offset] * scale,
        offsetY - layer.segments[offset + 1] * scale,
      )
      context.lineTo(
        offsetX + layer.segments[offset + 2] * scale,
        offsetY - layer.segments[offset + 3] * scale,
      )
    }
    context.strokeStyle = extruding ? '#f23a3a' : 'rgba(174, 174, 182, 0.65)'
    context.lineWidth = extruding ? 1.35 : 0.8
    context.lineCap = 'round'
    context.setLineDash(extruding ? [] : [5, 4])
    context.stroke()
  }
  renderKind(false)
  renderKind(true)
}

export function ToolpathInspector({
  active,
  artifact,
}: {
  active: boolean
  artifact: Artifact | null
}) {
  const workerRef = useRef<Worker | null>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [phase, setPhase] = useState<'idle' | 'loading' | 'ready' | 'error'>(
    artifact ? 'loading' : 'idle',
  )
  const [message, setMessage] = useState(
    artifact ? 'Reading persisted G-code off the UI thread…' : 'No G-code is recorded.',
  )
  const [summary, setSummary] = useState<ToolpathSummary | null>(null)
  const [layer, setLayer] = useState<LayerPayload | null>(null)
  const [layerIndex, setLayerIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [reducedMotion, setReducedMotion] = useState(
    () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false,
  )

  useEffect(() => {
    const query = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    if (!query) return
    const update = (event: MediaQueryListEvent): void => {
      setReducedMotion(event.matches)
      if (event.matches) setPlaying(false)
    }
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])

  useEffect(() => {
    if (!artifact) return
    const worker = new Worker(new URL('./toolpath.worker.ts', import.meta.url), { type: 'module' })
    workerRef.current = worker
    worker.onmessage = (event: MessageEvent<WorkerResponse>) => {
      const response = event.data
      if (response.type === 'ready') {
        setSummary(response.summary)
        setPhase('ready')
        setMessage('Toolpath index ready.')
      } else if (response.type === 'layer') {
        setLayer(response)
      } else {
        setPhase('error')
        setMessage(response.message)
        setPlaying(false)
      }
    }
    worker.onerror = () => {
      setPhase('error')
      setMessage('The isolated toolpath worker stopped unexpectedly.')
      setPlaying(false)
    }
    worker.postMessage({ type: 'load', url: artifact.download_url })
    return () => {
      worker.terminate()
      workerRef.current = null
    }
  }, [artifact])

  useEffect(() => {
    if (!summary) return
    workerRef.current?.postMessage({ type: 'layer', layerIndex })
  }, [layerIndex, summary])

  useEffect(() => {
    if (!active || !playing || !summary || reducedMotion) return
    const timer = window.setInterval(() => {
      setLayerIndex((current) => {
        if (current >= summary.layerCount - 1) {
          setPlaying(false)
          return current
        }
        return current + 1
      })
    }, 140)
    return () => window.clearInterval(timer)
  }, [active, playing, reducedMotion, summary])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !layer) return
    const render = () => drawLayer(canvas, layer)
    render()
    const observer = new ResizeObserver(render)
    if (canvas.parentElement) observer.observe(canvas.parentElement)
    return () => observer.disconnect()
  }, [layer])

  if (!artifact) {
    return (
      <div className="viewer-placeholder" aria-label="No toolpath playback available">
        <span>G</span>
        <strong>No G-code recorded</strong>
        <p>This journey stops before a slicer toolpath artifact becomes available.</p>
      </div>
    )
  }

  return (
    <div className="toolpath-inspector">
      <div className="toolpath-canvas-frame">
        <canvas
          ref={canvasRef}
          role="img"
          aria-label={
            layer
              ? `Top-down G-code playback for layer ${layer.layerIndex + 1} at ${layer.zMm.toFixed(2)} millimetres, with ${layer.extrusionSegmentCount} extrusion segments and ${layer.travelSegmentCount} travel segments${layer.truncated ? ', display sampled' : ''}`
              : 'G-code layer playback loading'
          }
        />
        {!layer || phase === 'error' ? (
          <div className={`viewer-status viewer-status-${phase}`} role="status">
            <strong>{phase === 'error' ? 'Toolpath unavailable' : 'Indexing G-code'}</strong>
            <span>{message}</span>
          </div>
        ) : null}
      </div>

      {summary ? (
        <div className="layer-controls">
          <div className="layer-readout">
            <strong>
              Layer {layerIndex + 1} / {summary.layerCount}
            </strong>
            <span>{layer ? `Z ${layer.zMm.toFixed(2)} mm` : 'Loading layer…'}</span>
          </div>
          <input
            aria-label="Displayed G-code layer"
            aria-valuetext={`Layer ${layerIndex + 1} of ${summary.layerCount}${layer ? `, Z ${layer.zMm.toFixed(2)} millimetres` : ''}`}
            type="range"
            min={0}
            max={Math.max(summary.layerCount - 1, 0)}
            value={layerIndex}
            onChange={(event) => setLayerIndex(Number(event.currentTarget.value))}
          />
          <div className="viewer-toolbar">
            <button
              type="button"
              onClick={() => setLayerIndex((current) => Math.max(current - 1, 0))}
              disabled={layerIndex === 0}
            >
              Previous layer
            </button>
            <button
              type="button"
              onClick={() => setPlaying((current) => !current)}
              disabled={reducedMotion || summary.layerCount < 2}
              title={reducedMotion ? 'Automatic playback is disabled by reduced-motion preference' : undefined}
            >
              {playing ? 'Pause' : 'Play layers'}
            </button>
            <button
              type="button"
              onClick={() => setLayerIndex((current) => Math.min(current + 1, summary.layerCount - 1))}
              disabled={layerIndex >= summary.layerCount - 1}
            >
              Next layer
            </button>
          </div>
          {reducedMotion ? (
            <p className="reduced-motion-note">
              Automatic playback is disabled by your reduced-motion preference. Previous and Next
              layer controls remain available.
            </p>
          ) : null}
        </div>
      ) : null}

      <ul className="toolpath-legend" aria-label="Toolpath line legend">
        <li><i className="legend-extrusion" />Solid line: extrusion motion</li>
        <li><i className="legend-travel" />Dashed line: travel motion</li>
      </ul>
      <div className="preview-boundary">
        <strong>Manufacturing playback — not engineering simulation</strong>
        <p>
          This top-down view replays recorded linear G-code moves. It does not model extrusion
          quality, collisions, adhesion, strength, temperature, or printer behavior.
        </p>
      </div>
      {summary && layer ? (
        <dl className="preview-metadata">
          <div>
            <dt>Recorded layers</dt>
            <dd>{summary.layerCount.toLocaleString()}</dd>
          </div>
          <div>
            <dt>All linear moves</dt>
            <dd>{summary.totalSegmentCount.toLocaleString()}</dd>
          </div>
          <div>
            <dt>Layer extrusion</dt>
            <dd>{layer.extrusionSegmentCount.toLocaleString()} segments</dd>
          </div>
          <div>
            <dt>Layer travel</dt>
            <dd>{layer.travelSegmentCount.toLocaleString()} segments</dd>
          </div>
          {layer.truncated ? (
            <div>
              <dt>Display sampling</dt>
              <dd>{layer.returnedSegmentCount.toLocaleString()} / {layer.sourceSegmentCount.toLocaleString()}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}
    </div>
  )
}
