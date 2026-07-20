import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import { parseGCodeToolpath } from './toolpath'

const realGcodePath = process.env.ARIAD_REAL_GCODE

describe.skipIf(!realGcodePath)('real persisted G-code toolpath', () => {
  it('parses the recorded Golden Part PrusaSlicer dialect', () => {
    const parsed = parseGCodeToolpath(readFileSync(realGcodePath!, 'utf-8'))

    expect(parsed.summary.layerCount).toBe(250)
    expect(parsed.summary.totalSegmentCount).toBeGreaterThan(100_000)
    expect(parsed.summary.extrusionSegmentCount).toBeGreaterThan(50_000)
    expect(parsed.summary.bounds.minX).toBeGreaterThanOrEqual(0)
    expect(parsed.summary.bounds.maxX).toBeLessThanOrEqual(220)
    expect(parsed.summary.bounds.minY).toBeGreaterThanOrEqual(0)
    expect(parsed.summary.bounds.maxY).toBeLessThanOrEqual(220)
  })
})
