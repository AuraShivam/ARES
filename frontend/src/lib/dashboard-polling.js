export function startVisibleDashboardPolling(refresh, {
  documentRef = document,
  windowRef = window,
  intervalMs = 30_000,
} = {}) {
  let timer
  let stopped = false
  let pollController

  async function poll() {
    if (stopped) return
    if (documentRef.visibilityState === 'visible') {
      pollController = new AbortController()
      await refresh(pollController.signal)
    }
    if (!stopped && documentRef.visibilityState === 'visible') {
      timer = windowRef.setTimeout(poll, intervalMs)
    }
  }

  function onVisibilityChange() {
    windowRef.clearTimeout(timer)
    pollController?.abort()
    if (documentRef.visibilityState === 'visible') poll()
  }

  timer = windowRef.setTimeout(poll, intervalMs)
  documentRef.addEventListener('visibilitychange', onVisibilityChange)

  return () => {
    stopped = true
    windowRef.clearTimeout(timer)
    pollController?.abort()
    documentRef.removeEventListener('visibilitychange', onVisibilityChange)
  }
}
