import { readFileSync } from 'node:fs'
import { Box3, Mesh, Vector3 } from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { describe, expect, it } from 'vitest'

const realGlbPath = process.env.ARIAD_REAL_GLB

describe.skipIf(!realGlbPath)('real persisted GLB preview', () => {
  it('loads through the selected Three.js GLTF parser with finite geometry', async () => {
    const bytes = readFileSync(realGlbPath!)
    const payload = new ArrayBuffer(bytes.byteLength)
    new Uint8Array(payload).set(bytes)
    const gltf = await new GLTFLoader().parseAsync(payload, '')
    const bounds = new Box3().setFromObject(gltf.scene)
    const size = bounds.getSize(new Vector3())
    let triangleCount = 0
    gltf.scene.traverse((item) => {
      if (!(item instanceof Mesh)) return
      const positions = item.geometry.getAttribute('position')
      triangleCount += item.geometry.index
        ? item.geometry.index.count / 3
        : positions.count / 3
    })

    expect(bounds.isEmpty()).toBe(false)
    expect([size.x, size.y, size.z].every(Number.isFinite)).toBe(true)
    expect(Math.min(size.x, size.y, size.z)).toBeGreaterThan(0)
    expect(triangleCount).toBeGreaterThan(1_000)
  })
})
