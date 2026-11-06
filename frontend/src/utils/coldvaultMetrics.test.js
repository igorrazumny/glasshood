import { describe, it, expect } from 'vitest'
import { metricsNotRead } from './coldvaultMetrics'

describe('metricsNotRead (REQ-GHA-025)', () => {
  it('gives the reason and the UTC time', () => {
    const at = Date.UTC(2026, 10, 6, 11, 5) / 1000
    expect(metricsNotRead({ read: false, reason: 'ColdVault refused the request (HTTP 403)', checked_at: at }))
      .toBe('ColdVault metrics not read: ColdVault refused the request (HTTP 403) · 11:05 UTC')
  })

  it('works before the first attempt', () => {
    expect(metricsNotRead({ read: false, reason: 'not read yet', checked_at: null }))
      .toBe('ColdVault metrics not read: not read yet')
  })
})
