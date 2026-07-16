import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(resolve(process.cwd(), 'src', 'styles.css'), 'utf8')

function cssColor(name: string): string {
  const match = css.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`))
  if (!match?.[1]) throw new Error(`CSS color --${name} is missing or is not a six-digit hex value`)
  return match[1]
}

function luminance(color: string): number {
  const channels = [1, 3, 5].map((offset) => Number.parseInt(color.slice(offset, offset + 2), 16) / 255)
  const linear = channels.map((channel) =>
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4,
  )
  return 0.2126 * linear[0]! + 0.7152 * linear[1]! + 0.0722 * linear[2]!
}

function contrast(first: string, second: string): number {
  const values = [luminance(first), luminance(second)].sort((left, right) => right - left)
  return (values[0]! + 0.05) / (values[1]! + 0.05)
}

describe('interface accessibility styles', () => {
  it('keeps normal text colors at WCAG AA contrast on their darkest common panels', () => {
    expect(contrast(cssColor('red'), cssColor('panel-raised'))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(cssColor('muted'), cssColor('panel-raised'))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(cssColor('white'), cssColor('panel-raised'))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(cssColor('bg'), cssColor('red'))).toBeGreaterThanOrEqual(4.5)
  })

  it('retains visible focus, skip-navigation, and reduced-motion rules', () => {
    expect(contrast(cssColor('focus'), cssColor('panel-raised'))).toBeGreaterThanOrEqual(3)
    expect(css).toMatch(/\.skip-link:focus-visible\s*\{[^}]*transform:\s*translateY\(0\)/s)
    expect(css).toMatch(/:focus-visible\s*\{[^}]*outline:\s*3px solid var\(--focus\)/s)
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)/)
    expect(css).toMatch(/\.comparison-launcher \.compare-button\s*\{[^}]*color:\s*var\(--bg\)/s)
  })
})
