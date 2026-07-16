import {
  MAX_TOOLPATH_BYTES,
  parseGCodeToolpath,
  sampledLayer,
  type ParsedToolpath,
  type ToolpathBounds,
  type ToolpathSummary,
} from './toolpath'

type WorkerRequest =
  | { type: 'load'; url: string }
  | { type: 'layer'; layerIndex: number }

type WorkerResponse =
  | { type: 'ready'; summary: ToolpathSummary }
  | {
      type: 'layer'
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
  | { type: 'error'; message: string }

const scope = self as unknown as {
  onmessage: ((event: MessageEvent<WorkerRequest>) => void) | null
  postMessage(message: WorkerResponse, transfer?: Transferable[]): void
}
let parsed: ParsedToolpath | null = null
let activeLoad: AbortController | null = null

function postLayer(layerIndex: number): void {
  if (!parsed) throw new Error('Toolpath data has not finished loading')
  const layer = parsed.layers[layerIndex]
  if (!layer) throw new Error(`Layer ${layerIndex + 1} is outside the recorded toolpath`)
  const sampled = sampledLayer(layer)
  const response: WorkerResponse = {
    type: 'layer',
    layerIndex,
    zMm: layer.zMm,
    bounds: layer.bounds,
    extrusionSegmentCount: layer.extrusionSegmentCount,
    travelSegmentCount: layer.travelSegmentCount,
    ...sampled,
  }
  scope.postMessage(response, [response.segments.buffer])
}

async function load(url: string): Promise<void> {
  activeLoad?.abort()
  const controller = new AbortController()
  activeLoad = controller
  parsed = null
  const response = await fetch(url, {
    headers: { Accept: 'text/x.gcode, text/plain' },
    signal: controller.signal,
  })
  if (!response.ok) throw new Error(`G-code request failed with status ${response.status}`)
  const recordedLength = Number(response.headers.get('content-length') ?? 0)
  if (recordedLength > MAX_TOOLPATH_BYTES) {
    throw new Error(`G-code exceeds the ${MAX_TOOLPATH_BYTES / (1024 * 1024)} MiB preview limit`)
  }
  const payload = await response.arrayBuffer()
  if (payload.byteLength > MAX_TOOLPATH_BYTES) {
    throw new Error(`G-code exceeds the ${MAX_TOOLPATH_BYTES / (1024 * 1024)} MiB preview limit`)
  }
  parsed = parseGCodeToolpath(new TextDecoder('utf-8', { fatal: false }).decode(payload))
  scope.postMessage({ type: 'ready', summary: parsed.summary })
}

scope.onmessage = (event) => {
  const request = event.data
  if (request.type === 'load') {
    void load(request.url).catch((reason: unknown) => {
      if (reason instanceof DOMException && reason.name === 'AbortError') return
      scope.postMessage({
        type: 'error',
        message: reason instanceof Error ? reason.message : 'The G-code could not be parsed.',
      })
    })
    return
  }
  try {
    postLayer(request.layerIndex)
  } catch (reason) {
    scope.postMessage({
      type: 'error',
      message: reason instanceof Error ? reason.message : 'The requested layer is unavailable.',
    })
  }
}
