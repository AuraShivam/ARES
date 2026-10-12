import test from 'node:test'
import assert from 'node:assert/strict'

import { startVisibleDashboardPolling } from '../src/lib/dashboard-polling.js'

function pollingHarness() {
  let nextTimerId = 0
  const timers = new Map()
  const listeners = new Map()
  const documentRef = {
    visibilityState: 'visible',
    addEventListener(name, callback) { listeners.set(name, callback) },
    removeEventListener(name, callback) {
      if (listeners.get(name) === callback) listeners.delete(name)
    },
  }
  const windowRef = {
    setTimeout(callback, delay) {
      const id = ++nextTimerId
      timers.set(id, { callback, delay })
      return id
    },
    clearTimeout(id) { timers.delete(id) },
  }
  return {
    documentRef,
    windowRef,
    timers,
    changeVisibility(state) {
      documentRef.visibilityState = state
      listeners.get('visibilitychange')?.()
    },
    async runNextTimer() {
      const [id, timer] = timers.entries().next().value || []
      assert.ok(timer, 'expected a scheduled polling timer')
      timers.delete(id)
      await timer.callback()
      return timer.delay
    },
    async flushMicrotasks() {
      await Promise.resolve()
      await Promise.resolve()
    },
  }
}

test('pauses while hidden and immediately refreshes when the tab becomes visible', async () => {
  const harness = pollingHarness()
  const signals = []
  const stop = startVisibleDashboardPolling(
    async (signal) => { signals.push(signal) },
    { documentRef: harness.documentRef, windowRef: harness.windowRef, intervalMs: 30_000 },
  )

  assert.equal(harness.timers.size, 1)
  assert.equal(await harness.runNextTimer(), 30_000)
  assert.equal(signals.length, 1)
  assert.equal(harness.timers.size, 1)

  harness.changeVisibility('hidden')
  assert.equal(signals[0].aborted, true)
  assert.equal(harness.timers.size, 0)

  harness.changeVisibility('visible')
  await harness.flushMicrotasks()
  assert.equal(signals.length, 2)
  assert.equal(harness.timers.size, 1)

  stop()
  assert.equal(harness.timers.size, 0)
})
