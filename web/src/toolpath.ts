export const TOOLPATH_RECORD_SIZE = 5
export const MAX_TOOLPATH_BYTES = 64 * 1024 * 1024
export const MAX_TOOLPATH_SEGMENTS = 1_000_000
export const MAX_RENDERED_LAYER_SEGMENTS = 20_000

export interface ToolpathBounds {
  minX: number
  maxX: number
  minY: number
  maxY: number
}

export interface ToolpathLayer {
  index: number
  zMm: number
  segments: Float32Array
  extrusionSegmentCount: number
  travelSegmentCount: number
  bounds: ToolpathBounds
}

export interface ToolpathSummary {
  layerCount: number
  totalSegmentCount: number
  extrusionSegmentCount: number
  travelSegmentCount: number
  bounds: ToolpathBounds
  featureCounts: Record<string, number>
  unsupportedArcCount: number
  warnings: string[]
}

export interface ParsedToolpath {
  summary: ToolpathSummary
  layers: ToolpathLayer[]
}

interface MotionState {
  x: number
  y: number
  z: number
  e: number
  absoluteXyz: boolean
  absoluteExtrusion: boolean
}

interface MutableLayer {
  index: number
  zMm: number
  segments: number[]
  extrusionSegmentCount: number
  travelSegmentCount: number
  bounds: ToolpathBounds
}

const commandPattern = /^([GMT])(\d+(?:\.\d+)?)$/i
const tokenPattern = /^([A-Za-z])([-+]?(?:\d+(?:\.\d*)?|\.\d+))$/

function emptyBounds(): ToolpathBounds {
  return {
    minX: Number.POSITIVE_INFINITY,
    maxX: Number.NEGATIVE_INFINITY,
    minY: Number.POSITIVE_INFINITY,
    maxY: Number.NEGATIVE_INFINITY,
  }
}

function includePoint(bounds: ToolpathBounds, x: number, y: number): void {
  bounds.minX = Math.min(bounds.minX, x)
  bounds.maxX = Math.max(bounds.maxX, x)
  bounds.minY = Math.min(bounds.minY, y)
  bounds.maxY = Math.max(bounds.maxY, y)
}

function finiteBounds(bounds: ToolpathBounds): ToolpathBounds {
  if (Number.isFinite(bounds.minX)) return bounds
  return { minX: 0, maxX: 0, minY: 0, maxY: 0 }
}

function createLayer(index: number, zMm: number): MutableLayer {
  return {
    index,
    zMm,
    segments: [],
    extrusionSegmentCount: 0,
    travelSegmentCount: 0,
    bounds: emptyBounds(),
  }
}

function argumentsFor(tokens: string[]): Record<string, number> {
  const result: Record<string, number> = {}
  for (const token of tokens) {
    const match = tokenPattern.exec(token)
    if (match) result[match[1].toUpperCase()] = Number(match[2])
  }
  return result
}

export function parseGCodeToolpath(text: string): ParsedToolpath {
  const explicitLayerMarkers = /^(?:;LAYER_CHANGE|;LAYER:)/m.test(text)
  const layers: MutableLayer[] = []
  const state: MotionState = {
    x: 0,
    y: 0,
    z: 0,
    e: 0,
    absoluteXyz: true,
    absoluteExtrusion: true,
  }
  const featureCounts = new Map<string, number>()
  let currentLayer: MutableLayer | null = null
  let currentFeature = 'Unclassified extrusion'
  let unsupportedArcCount = 0
  let totalSegmentCount = 0
  let sawMillimetreUnits = false
  let sawInchUnits = false

  const beginLayer = (zMm: number): MutableLayer => {
    const layer = createLayer(layers.length, zMm)
    layers.push(layer)
    return layer
  }

  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (line === ';LAYER_CHANGE' || line.startsWith(';LAYER:')) {
      currentLayer = beginLayer(state.z)
      continue
    }
    if (line.startsWith(';Z:')) {
      const z = Number(line.slice(3))
      if (Number.isFinite(z)) {
        state.z = z
        if (currentLayer) currentLayer.zMm = z
      }
      continue
    }
    if (line.startsWith(';TYPE:')) {
      currentFeature = line.slice(6).trim() || 'Unclassified extrusion'
      continue
    }

    const code = line.split(';', 1)[0].trim()
    if (!code) continue
    const tokens = code.split(/\s+/)
    const commandMatch = commandPattern.exec(tokens[0])
    if (!commandMatch) continue
    const command = `${commandMatch[1].toUpperCase()}${Number(commandMatch[2])}`
    const args = argumentsFor(tokens.slice(1))

    if (command === 'G20') {
      sawInchUnits = true
      continue
    }
    if (command === 'G21') {
      sawMillimetreUnits = true
      continue
    }
    if (command === 'G90') {
      state.absoluteXyz = true
      continue
    }
    if (command === 'G91') {
      state.absoluteXyz = false
      continue
    }
    if (command === 'M82') {
      state.absoluteExtrusion = true
      continue
    }
    if (command === 'M83') {
      state.absoluteExtrusion = false
      continue
    }
    if (command === 'G92') {
      for (const axis of ['X', 'Y', 'Z', 'E'] as const) {
        const key = axis.toLowerCase() as 'x' | 'y' | 'z' | 'e'
        if (args[axis] !== undefined) state[key] = args[axis]
      }
      continue
    }
    if (command === 'G2' || command === 'G3') {
      unsupportedArcCount += 1
      continue
    }
    if (command !== 'G0' && command !== 'G1') continue

    const startX = state.x
    const startY = state.y
    const nextX =
      args.X === undefined ? state.x : state.absoluteXyz ? args.X : state.x + args.X
    const nextY =
      args.Y === undefined ? state.y : state.absoluteXyz ? args.Y : state.y + args.Y
    const nextZ =
      args.Z === undefined ? state.z : state.absoluteXyz ? args.Z : state.z + args.Z
    let extrusionDelta = 0
    if (args.E !== undefined) {
      extrusionDelta = state.absoluteExtrusion ? args.E - state.e : args.E
      state.e = state.absoluteExtrusion ? args.E : state.e + args.E
    }
    state.x = nextX
    state.y = nextY
    state.z = nextZ

    const hasXyMotion = Math.abs(nextX - startX) > 1e-7 || Math.abs(nextY - startY) > 1e-7
    if (!hasXyMotion) continue
    const extruding = extrusionDelta > 1e-7
    if (!explicitLayerMarkers && extruding) {
      if (!currentLayer || Math.abs(currentLayer.zMm - nextZ) > 1e-4) {
        currentLayer = beginLayer(nextZ)
      }
    }
    if (!currentLayer) continue

    currentLayer.segments.push(startX, startY, nextX, nextY, extruding ? 1 : 0)
    includePoint(currentLayer.bounds, startX, startY)
    includePoint(currentLayer.bounds, nextX, nextY)
    if (extruding) {
      currentLayer.extrusionSegmentCount += 1
      featureCounts.set(currentFeature, (featureCounts.get(currentFeature) ?? 0) + 1)
    } else {
      currentLayer.travelSegmentCount += 1
    }
    totalSegmentCount += 1
    if (totalSegmentCount > MAX_TOOLPATH_SEGMENTS) {
      throw new Error(`Toolpath exceeds the ${MAX_TOOLPATH_SEGMENTS.toLocaleString()} segment limit`)
    }
  }

  if (sawInchUnits) throw new Error('Inch-unit G-code is not supported by this millimetre viewport')
  if (!sawMillimetreUnits) throw new Error('The G-code does not declare G21 millimetre units')
  const nonemptyLayers = layers.filter((layer) => layer.segments.length > 0)
  if (nonemptyLayers.length === 0) throw new Error('No layer toolpath segments were found')

  const globalBounds = emptyBounds()
  let extrusionSegmentCount = 0
  let travelSegmentCount = 0
  const finalizedLayers = nonemptyLayers.map((layer, index) => {
    const bounds = finiteBounds(layer.bounds)
    includePoint(globalBounds, bounds.minX, bounds.minY)
    includePoint(globalBounds, bounds.maxX, bounds.maxY)
    extrusionSegmentCount += layer.extrusionSegmentCount
    travelSegmentCount += layer.travelSegmentCount
    return {
      index,
      zMm: layer.zMm,
      segments: new Float32Array(layer.segments),
      extrusionSegmentCount: layer.extrusionSegmentCount,
      travelSegmentCount: layer.travelSegmentCount,
      bounds,
    }
  })
  const warnings = [
    'Playback visualizes recorded G-code motion; it is not structural, thermal, fluid, or physical simulation.',
  ]
  if (unsupportedArcCount > 0) {
    warnings.push(`${unsupportedArcCount} arc command(s) are omitted from this linear-segment view.`)
  }
  return {
    summary: {
      layerCount: finalizedLayers.length,
      totalSegmentCount,
      extrusionSegmentCount,
      travelSegmentCount,
      bounds: finiteBounds(globalBounds),
      featureCounts: Object.fromEntries([...featureCounts].sort(([left], [right]) => left.localeCompare(right))),
      unsupportedArcCount,
      warnings,
    },
    layers: finalizedLayers,
  }
}

export function sampledLayer(layer: ToolpathLayer): {
  segments: Float32Array
  sourceSegmentCount: number
  returnedSegmentCount: number
  truncated: boolean
} {
  const sourceSegmentCount = layer.segments.length / TOOLPATH_RECORD_SIZE
  if (sourceSegmentCount <= MAX_RENDERED_LAYER_SEGMENTS) {
    return {
      segments: layer.segments.slice(),
      sourceSegmentCount,
      returnedSegmentCount: sourceSegmentCount,
      truncated: false,
    }
  }
  const stride = Math.ceil(sourceSegmentCount / MAX_RENDERED_LAYER_SEGMENTS)
  const returnedSegmentCount = Math.ceil(sourceSegmentCount / stride)
  const sampled = new Float32Array(returnedSegmentCount * TOOLPATH_RECORD_SIZE)
  let target = 0
  for (let source = 0; source < sourceSegmentCount; source += stride) {
    const offset = source * TOOLPATH_RECORD_SIZE
    sampled.set(layer.segments.subarray(offset, offset + TOOLPATH_RECORD_SIZE), target)
    target += TOOLPATH_RECORD_SIZE
  }
  return {
    segments: sampled,
    sourceSegmentCount,
    returnedSegmentCount,
    truncated: true,
  }
}
