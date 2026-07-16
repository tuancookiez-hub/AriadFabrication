import { useEffect, useRef, useState } from 'react'
import type { Material, Mesh, Object3D, PerspectiveCamera, Texture, WebGLRenderer } from 'three'
import type { OrbitControls } from 'three/addons/controls/OrbitControls.js'

import type { Artifact } from './types'

const MAX_MODEL_BYTES = 64 * 1024 * 1024
const MAX_MODEL_TRIANGLES = 2_000_000

type ViewerState =
  | { phase: 'idle'; message: string }
  | { phase: 'loading'; message: string }
  | { phase: 'ready'; message: string; triangleCount: number; dimensions: string }
  | { phase: 'error'; message: string }

function disposeModel(root: Object3D): void {
  root.traverse((child) => {
    const mesh = child as Mesh
    mesh.geometry?.dispose()
    const materials = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : []
    for (const material of materials as Material[]) {
      for (const value of Object.values(material)) {
        const texture = value as Texture | undefined
        if (texture?.isTexture) texture.dispose()
      }
      material.dispose()
    }
  })
}

function formatBytes(value: number | null): string {
  if (value === null) return 'size unrecorded'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`
}

export function ModelInspector({ artifact }: { artifact: Artifact | null }) {
  const hostRef = useRef<HTMLDivElement>(null)
  const resetCameraRef = useRef<(() => void) | null>(null)
  const [state, setState] = useState<ViewerState>(() =>
    artifact
      ? { phase: 'loading', message: 'Loading checksum-verified GLB preview…' }
      : { phase: 'idle', message: 'No GLB preview is recorded for this revision.' },
  )

  useEffect(() => {
    if (!artifact) return

    const hostElement: HTMLDivElement = hostRef.current!
    if (!hostElement) return
    const selectedArtifact = artifact
    const abortController = new AbortController()
    let cancelled = false
    let renderer: WebGLRenderer | null = null
    let controls: OrbitControls | null = null
    let camera: PerspectiveCamera | null = null
    let model: Object3D | null = null
    let resizeObserver: ResizeObserver | null = null

    async function initialise(): Promise<void> {
      try {
        if (
          selectedArtifact.size_bytes !== null &&
          selectedArtifact.size_bytes > MAX_MODEL_BYTES
        ) {
          throw new Error(`GLB exceeds the ${MAX_MODEL_BYTES / (1024 * 1024)} MiB preview limit`)
        }
        const [THREE, loaderModule, controlsModule] = await Promise.all([
          import('three'),
          import('three/addons/loaders/GLTFLoader.js'),
          import('three/addons/controls/OrbitControls.js'),
        ])
        if (cancelled) return

        const scene = new THREE.Scene()
        scene.background = new THREE.Color(0x0d0d0f)
        camera = new THREE.PerspectiveCamera(36, 1, 0.01, 100000)
        renderer = new THREE.WebGLRenderer({
          antialias: true,
          powerPreference: 'high-performance',
        })
        renderer.outputColorSpace = THREE.SRGBColorSpace
        renderer.toneMapping = THREE.ACESFilmicToneMapping
        renderer.toneMappingExposure = 1.05
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
        renderer.domElement.className = 'model-canvas'
        renderer.domElement.tabIndex = 0
        renderer.domElement.setAttribute('role', 'img')
        renderer.domElement.setAttribute(
          'aria-label',
          'Interactive tessellated model preview. Drag to orbit, scroll to zoom, and use arrow keys to pan.',
        )
        hostElement.replaceChildren(renderer.domElement)

        scene.add(new THREE.HemisphereLight(0xffffff, 0x2d1010, 2.4))
        const keyLight = new THREE.DirectionalLight(0xffffff, 3.2)
        keyLight.position.set(3, 5, 4)
        scene.add(keyLight)
        const rimLight = new THREE.DirectionalLight(0xef2929, 1.7)
        rimLight.position.set(-4, 2, -3)
        scene.add(rimLight)

        const response = await fetch(selectedArtifact.download_url, {
          headers: { Accept: 'model/gltf-binary' },
          signal: abortController.signal,
        })
        if (!response.ok) throw new Error(`GLB request failed with status ${response.status}`)
        const recordedLength = Number(response.headers.get('content-length') ?? 0)
        if (recordedLength > MAX_MODEL_BYTES) {
          throw new Error(`GLB exceeds the ${MAX_MODEL_BYTES / (1024 * 1024)} MiB preview limit`)
        }
        const payload = await response.arrayBuffer()
        if (payload.byteLength > MAX_MODEL_BYTES) {
          throw new Error(`GLB exceeds the ${MAX_MODEL_BYTES / (1024 * 1024)} MiB preview limit`)
        }
        if (cancelled) return
        const loader = new loaderModule.GLTFLoader()
        const gltf = await loader.parseAsync(payload, '')
        if (cancelled) {
          disposeModel(gltf.scene)
          return
        }
        model = gltf.scene

        let triangleCount = 0
        model.traverse((item) => {
          const mesh = item as Mesh
          if (!mesh.isMesh || !mesh.geometry) return
          const positions = mesh.geometry.getAttribute('position')
          triangleCount += mesh.geometry.index
            ? mesh.geometry.index.count / 3
            : positions.count / 3
        })
        if (triangleCount > MAX_MODEL_TRIANGLES) {
          throw new Error(
            `GLB exceeds the ${MAX_MODEL_TRIANGLES.toLocaleString()} triangle preview limit`,
          )
        }

        const bounds = new THREE.Box3().setFromObject(model)
        if (bounds.isEmpty()) throw new Error('The GLB preview contains no visible geometry')
        const centre = bounds.getCenter(new THREE.Vector3())
        const size = bounds.getSize(new THREE.Vector3())
        model.position.sub(centre)
        scene.add(model)

        const maximumDimension = Math.max(size.x, size.y, size.z, 1)
        camera.near = Math.max(maximumDimension / 1000, 0.01)
        camera.far = maximumDimension * 100
        camera.updateProjectionMatrix()

        const initialPosition = new THREE.Vector3(
          maximumDimension * 1.35,
          maximumDimension * 0.9,
          maximumDimension * 1.5,
        )
        camera.position.copy(initialPosition)
        camera.lookAt(0, 0, 0)

        controls = new controlsModule.OrbitControls(camera, renderer.domElement)
        controls.enableDamping = false
        controls.minDistance = maximumDimension * 0.35
        controls.maxDistance = maximumDimension * 12
        controls.target.set(0, 0, 0)
        controls.listenToKeyEvents(renderer.domElement)
        controls.update()

        const gridSize = maximumDimension * 2.4
        const grid = new THREE.GridHelper(gridSize, 12, 0x7f2020, 0x29292d)
        grid.position.y = -size.y / 2
        scene.add(grid)

        const render = (): void => {
          if (renderer && camera) renderer.render(scene, camera)
        }
        const resize = (): void => {
          if (!renderer || !camera) return
          const width = Math.max(hostElement.clientWidth, 320)
          const height = Math.max(hostElement.clientHeight, 300)
          renderer.setSize(width, height, false)
          camera.aspect = width / height
          camera.updateProjectionMatrix()
          render()
        }
        controls.addEventListener('change', render)
        resizeObserver = new ResizeObserver(resize)
        resizeObserver.observe(hostElement)
        resize()

        const reset = (): void => {
          if (!camera || !controls) return
          camera.position.copy(initialPosition)
          controls.target.set(0, 0, 0)
          controls.update()
          render()
        }
        resetCameraRef.current = reset
        render()
        setState({
          phase: 'ready',
          message: 'Preview loaded from the persisted artifact.',
          triangleCount,
          dimensions: `${size.x.toFixed(1)} × ${size.y.toFixed(1)} × ${size.z.toFixed(1)} mm`,
        })
      } catch (reason) {
        if (cancelled || abortController.signal.aborted) return
        setState({
          phase: 'error',
          message: reason instanceof Error ? reason.message : 'The GLB preview could not be rendered.',
        })
      }
    }

    void initialise()
    return () => {
      cancelled = true
      abortController.abort()
      resetCameraRef.current = null
      resizeObserver?.disconnect()
      controls?.stopListenToKeyEvents()
      controls?.dispose()
      if (model) disposeModel(model)
      renderer?.dispose()
      renderer?.forceContextLoss()
      hostElement.replaceChildren()
    }
  }, [artifact])

  if (!artifact) {
    return (
      <div className="viewer-placeholder" aria-label="No 3D preview available">
        <span>3D</span>
        <strong>No GLB preview recorded</strong>
        <p>This journey stops before a browser-preview artifact becomes available.</p>
      </div>
    )
  }

  return (
    <div className="model-inspector">
      <div className="model-viewport" ref={hostRef} aria-busy={state.phase === 'loading'}>
        {state.phase !== 'ready' ? (
          <div className={`viewer-status viewer-status-${state.phase}`} role="status">
            <strong>{state.phase === 'error' ? 'Preview unavailable' : 'Preparing model'}</strong>
            <span>{state.message}</span>
          </div>
        ) : null}
      </div>
      <div className="viewer-toolbar">
        <button
          type="button"
          onClick={() => resetCameraRef.current?.()}
          disabled={state.phase !== 'ready'}
        >
          Reset camera
        </button>
        <a href={artifact.download_url}>Open GLB</a>
      </div>
      <div className="preview-boundary">
        <strong>Geometry preview — not validation</strong>
        <p>
          This is a tessellated view of a persisted GLB artifact. STEP remains the exact geometry;
          this viewport proves neither strength, thermal behavior, nor physical print success.
        </p>
      </div>
      <dl className="preview-metadata">
        <div>
          <dt>Artifact</dt>
          <dd>{formatBytes(artifact.size_bytes)}</dd>
        </div>
        <div>
          <dt>Checksum</dt>
          <dd title={artifact.checksum_sha256}>{artifact.checksum_sha256.slice(0, 12)}…</dd>
        </div>
        {state.phase === 'ready' ? (
          <>
            <div>
              <dt>Preview bounds</dt>
              <dd>{state.dimensions}</dd>
            </div>
            <div>
              <dt>Rendered triangles</dt>
              <dd>{state.triangleCount.toLocaleString()}</dd>
            </div>
          </>
        ) : null}
      </dl>
    </div>
  )
}
