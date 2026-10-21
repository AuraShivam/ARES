import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { NAV_GROUPS, SECTIONS, TABLE_COLUMNS } from '../config/navigation.js'
import { clearAccessToken, eventsWebSocketUrl, getAccessToken, request, setAccessToken, setUnauthorizedHandler } from '../lib/api.js'
import { formatRelativeTime, rowsFrom } from '../lib/format.js'
import { startVisibleDashboardPolling } from '../lib/dashboard-polling.js'
import { OverviewPage, LoadingState } from '../features/overview/OverviewPage.jsx'
import DataTable from '../features/records/DataTable.jsx'
import { AssessmentModal, DisruptionForm, MovementForm, PurchaseOrderForm } from '../features/actions/Dialogs.jsx'
import ImportDialog from '../features/imports/ImportDialog.jsx'
import ResponsePlanDialog from '../features/response-plans/ResponsePlanDialog.jsx'
import LoginScreen from '../features/auth/LoginScreen.jsx'
import ExternalFeedStatus from '../features/imports/ExternalFeedStatus.jsx'
import RiskIntelligencePage from '../features/risk/RiskIntelligencePage.jsx'

const DASHBOARD_REFRESH_INTERVAL_MS = 30_000

function App() {
  const [auth, setAuth] = useState(null)
  const [authInitializing, setAuthInitializing] = useState(true)
  const [authSaving, setAuthSaving] = useState(false)
  const [authError, setAuthError] = useState('')
  const [section, setSection] = useState('overview')
  const [expandedNavGroup, setExpandedNavGroup] = useState('Monitor')
  const [overview, setOverview] = useState(null)
  const [apiHealth, setApiHealth] = useState(null)
  const [feedStatus, setFeedStatus] = useState(null)
  const [riskData, setRiskData] = useState({ assessments: [], alerts: [], disruptions: [], outcomes: [], policy: null, calibration: null, predictive: null, shipments: [] })
  const [records, setRecords] = useState([])
  const [homeData, setHomeData] = useState({ disruptions: [], shipments: [], inventory: [], riskAlerts: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [assessment, setAssessment] = useState(null)
  const [busyId, setBusyId] = useState('')
  const [saving, setSaving] = useState(false)
  const [modal, setModal] = useState('')
  const [selectedPlan, setSelectedPlan] = useState(null)
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState({ key: '', direction: 'asc' })
  const [lastUpdated, setLastUpdated] = useState(null)
  const [refreshState, setRefreshState] = useState('connecting')
  const [liveUpdates, setLiveUpdates] = useState('connecting')
  const [clockNow, setClockNow] = useState(Date.now())

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setAuth(null)
      setAuthError('Your ARES session expired. Sign in again.')
      setOverview(null)
      setApiHealth(null)
      setRecords([])
      setHomeData({ disruptions: [], shipments: [], inventory: [], riskAlerts: [] })
      setRiskData({ assessments: [], alerts: [], disruptions: [], outcomes: [], policy: null, calibration: null, predictive: null, shipments: [] })
      setLastUpdated(null)
      setRefreshState('connecting')
      setModal('')
      setSelectedPlan(null)
    })
    let savedToken = ''
    try { savedToken = window.sessionStorage.getItem('ares-api-token') || '' } catch { savedToken = '' }
    if (!savedToken) {
      setAuthInitializing(false)
      return () => setUnauthorizedHandler(null)
    }
    setAccessToken(savedToken)
    request('/auth/me/')
      .then(setAuth)
      .catch(() => {
        clearAccessToken()
        try { window.sessionStorage.removeItem('ares-api-token') } catch { /* Storage may be unavailable in embedded contexts. */ }
      })
      .finally(() => setAuthInitializing(false))
    return () => setUnauthorizedHandler(null)
  }, [])

  const refresh = useCallback(async (signal, silent = false) => {
    setLoading(true)
    if (!silent) setError('')
    try {
      const [summary, health] = await Promise.all([
        request('/overview/', { signal }),
        request('/health/', { signal }),
      ])
      setOverview(summary)
      setApiHealth(health)

      if (section === 'overview') {
        const [disruptions, shipments, inventory, riskAlerts] = await Promise.all([
          request('/disruptions/', { signal }),
          request('/shipments/', { signal }),
          request('/inventory/', { signal }),
          request('/risk/alerts/?status=active', { signal }),
        ])
        setHomeData({ disruptions: rowsFrom(disruptions), shipments: rowsFrom(shipments), inventory: rowsFrom(inventory), riskAlerts: rowsFrom(riskAlerts) })
      } else if (section === 'risk-intelligence') {
        const [assessments, alerts, disruptions, policy, calibration, outcomes, predictive, shipments] = await Promise.all([
          request('/risk/assessments/', { signal }),
          request('/risk/alerts/', { signal }),
          request('/disruptions/', { signal }),
          request('/risk/policy/', { signal }),
          request('/risk/calibration/', { signal }),
          auth?.is_approver ? request('/risk/outcomes/', { signal }) : Promise.resolve([]),
          request('/risk/predictive/', { signal }),
          request('/shipments/', { signal }),
        ])
        setRiskData({
          assessments: rowsFrom(assessments),
          alerts: rowsFrom(alerts),
          disruptions: rowsFrom(disruptions),
          outcomes: rowsFrom(outcomes),
          policy,
          calibration,
          predictive,
          shipments: rowsFrom(shipments),
        })
        setRecords([])
        setFeedStatus(null)
      } else {
        const data = await request(`/${section}/`, { signal })
        setRecords(rowsFrom(data))
        if (section === 'imports') {
          const sources = await request('/feeds/status/', { signal })
          setFeedStatus(sources.sources?.[0] || null)
        } else {
          setFeedStatus(null)
        }
      }
      setLastUpdated(new Date())
      setRefreshState('connected')
      return true
    } catch (requestError) {
      if (requestError.name !== 'AbortError') {
        setRefreshState('stale')
        if (!silent) setError(requestError.message)
      }
      return false
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [section, auth?.is_approver])

  useEffect(() => {
    if (!auth || authInitializing) return undefined
    const controller = new AbortController()
    refresh(controller.signal)
    return () => controller.abort()
  }, [refresh, auth, authInitializing])

  useEffect(() => {
    if (!auth || authInitializing) return undefined
    return startVisibleDashboardPolling(
      (signal) => refresh(signal, true),
      { intervalMs: DASHBOARD_REFRESH_INTERVAL_MS },
    )
  }, [refresh, auth, authInitializing])

  useEffect(() => {
    if (!auth || authInitializing) return undefined

    let disposed = false
    let socket = null
    let reconnectTimer = null
    let refreshTimer = null
    let reconnectAttempt = 0

    function scheduleReconnect(code) {
      if (disposed) return
      setLiveUpdates(code === 4401 ? 'expired' : 'reconnecting')
      if (code === 4401) return
      const delay = Math.min(30_000, 1_000 * (2 ** Math.min(reconnectAttempt, 5)))
      reconnectAttempt += 1
      reconnectTimer = window.setTimeout(connect, delay)
    }

    function connect() {
      if (disposed) return
      setLiveUpdates('connecting')
      try {
        socket = new WebSocket(eventsWebSocketUrl())
      } catch {
        scheduleReconnect(0)
        return
      }

      const currentSocket = socket
      currentSocket.addEventListener('open', () => {
        const token = getAccessToken()
        if (!token) {
          currentSocket.close(4401, 'Authentication required')
          return
        }
        currentSocket.send(JSON.stringify({ type: 'authenticate', token }))
      })
      currentSocket.addEventListener('message', (message) => {
        let event
        try { event = JSON.parse(message.data) } catch { return }
        if (event.type === 'ready') {
          reconnectAttempt = 0
          setLiveUpdates('connected')
        } else if (event.type === 'data_changed') {
          window.clearTimeout(refreshTimer)
          refreshTimer = window.setTimeout(() => {
            refreshTimer = null
            if (!disposed && document.visibilityState === 'visible') refresh(undefined, true)
          }, 500)
        }
      })
      currentSocket.addEventListener('close', (event) => scheduleReconnect(event.code))
      currentSocket.addEventListener('error', () => currentSocket.close())
    }

    connect()
    return () => {
      disposed = true
      window.clearTimeout(reconnectTimer)
      window.clearTimeout(refreshTimer)
      socket?.close(1000, 'Dashboard closed')
    }
  }, [refresh, auth, authInitializing])

  useEffect(() => {
    const timer = window.setInterval(() => setClockNow(Date.now()), DASHBOARD_REFRESH_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!notice) return undefined
    const timer = window.setTimeout(() => setNotice(''), 4500)
    return () => window.clearTimeout(timer)
  }, [notice])

  useEffect(() => {
    function onKeyDown(event) {
      if (event.key === 'Escape') {
        setModal('')
        setAssessment(null)
        setSelectedPlan(null)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  function navigate(nextSection) {
    setSection(nextSection)
    const group = NAV_GROUPS.find((item) => item.items.some(([key]) => key === nextSection))
    if (group) setExpandedNavGroup(group.title)
    setSearch('')
    setSort({ key: '', direction: 'asc' })
    setAssessment(null)
    setSelectedPlan(null)
  }

  async function assessRisk(disruptionId) {
    setBusyId(disruptionId)
    setAssessment(null)
    setError('')
    try {
      setAssessment(await request('/risk/assess/', { method: 'POST', body: JSON.stringify({ disruption_id: disruptionId }) }))
      const [summary, alerts] = await Promise.all([request('/overview/'), request('/risk/alerts/?status=active')])
      setOverview(summary)
      setHomeData((current) => ({ ...current, riskAlerts: rowsFrom(alerts) }))
      setLastUpdated(new Date())
      setRefreshState('connected')
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusyId('')
    }
  }

  async function saveRiskOutcome(payload) {
    setBusyId(payload.disruption_id)
    setError('')
    try {
      await request('/risk/outcomes/', { method: 'POST', body: JSON.stringify(payload) })
      setNotice('Verified outcome saved to the audit history.')
      await refresh()
      return true
    } catch (requestError) {
      setError(requestError.message)
      return false
    } finally {
      setBusyId('')
    }
  }

  async function verifyShipmentDelivery(shipmentId, payload) {
    setBusyId(shipmentId)
    setError('')
    try {
      await request(`/shipments/${shipmentId}/verify-delivery/`, {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      setNotice('Delivery outcome verified and added to the model training history.')
      await refresh()
      return true
    } catch (requestError) {
      setError(requestError.message)
      return false
    } finally {
      setBusyId('')
    }
  }

  async function markReviewed(disruptionId) {
    try {
      await request(`/disruptions/${disruptionId}/`, { method: 'PATCH', body: JSON.stringify({ status: 'review' }) })
      setAssessment(null)
      setNotice('Disruption marked as under review.')
      await refresh()
    } catch (requestError) {
      setError(requestError.message)
    }
  }

  async function createDisruption(payload) {
    setSaving(true)
    try {
      const created = await request('/disruptions/', { method: 'POST', body: JSON.stringify(payload) })
      setModal('')
      navigate('disruptions')
      setNotice('Disruption created. Preparing its assessment brief…')
      try {
        const [disruptions, summary, alerts] = await Promise.all([
          request('/disruptions/'), request('/overview/'), request('/risk/alerts/?status=active'),
        ])
        setRecords(rowsFrom(disruptions))
        setOverview(summary)
        setHomeData((current) => ({ ...current, riskAlerts: rowsFrom(alerts) }))
        setLastUpdated(new Date())
        setRefreshState('connected')
      } catch (requestError) {
        setError(`Disruption created, but the list could not refresh: ${requestError.message}`)
      }
      try {
        setAssessment(await request('/risk/assess/', { method: 'POST', body: JSON.stringify({ disruption_id: created.id }) }))
      } catch (requestError) {
        setError(`Disruption created, but assessment failed: ${requestError.message}`)
      }
    } finally {
      setSaving(false)
    }
  }

  async function recordMovement(payload) {
    setSaving(true)
    try {
      await request('/inventory-movements/', { method: 'POST', body: JSON.stringify(payload) })
      setModal('')
      setNotice('Stock movement recorded and inventory balance updated.')
      navigate('inventory-movements')
    } finally {
      setSaving(false)
    }
  }

  async function createPurchaseOrder(payload) {
    setSaving(true)
    try {
      await request('/purchase-orders/', { method: 'POST', body: JSON.stringify(payload) })
      setModal('')
      setNotice('Purchase order created.')
      await refresh()
    } finally {
      setSaving(false)
    }
  }

  async function completeImport(batch) {
    setModal('')
    setNotice(`Import committed: ${batch.created_rows} created, ${batch.updated_rows} updated, ${batch.skipped_rows} skipped.`)
    await refresh()
  }

  async function responsePlanCreated(plan) {
    setModal('')
    setNotice(`Response plan created for “${plan.disruption_title}”. Submit it for approval when ready.`)
    await refresh()
  }

  async function responsePlanChanged(plan) {
    setNotice(`Response plan updated: ${plan.title}.`)
    await refresh()
  }

  async function signIn(credentials) {
    setAuthSaving(true)
    setAuthError('')
    try {
      const session = await request('/auth/login/', { method: 'POST', body: JSON.stringify(credentials) })
      setAccessToken(session.token)
      try { window.sessionStorage.setItem('ares-api-token', session.token) } catch { /* The in-memory token still works for this page session. */ }
      setAuth(session.user)
    } catch (requestError) {
      setAuthError(requestError.message)
    } finally {
      setAuthSaving(false)
    }
  }

  async function signOut() {
    try { await request('/auth/logout/', { method: 'POST' }) } catch { /* Local sign-out still removes this browser's token. */ }
    clearAccessToken()
    try { window.sessionStorage.removeItem('ares-api-token') } catch { /* Storage may be unavailable in embedded contexts. */ }
    setAuth(null)
    setNotice('')
    setAssessment(null)
    setModal('')
    setSelectedPlan(null)
    setOverview(null)
    setApiHealth(null)
    setRecords([])
    setHomeData({ disruptions: [], shipments: [], inventory: [], riskAlerts: [] })
    setRiskData({ assessments: [], alerts: [], disruptions: [], outcomes: [], policy: null, calibration: null, predictive: null, shipments: [] })
    setLastUpdated(null)
    setRefreshState('connecting')
  }

  const current = SECTIONS[section] || SECTIONS.overview
  const columns = TABLE_COLUMNS[section] || []
  const visibleRecords = useMemo(() => {
    const query = search.trim().toLowerCase()
    let result = records
    if (query) {
      result = result.filter((record) => JSON.stringify(record).toLowerCase().includes(query))
    }
    if (sort.key) {
      result = [...result].sort((left, right) => {
        const a = left[sort.key] ?? ''
        const b = right[sort.key] ?? ''
        const numberA = Number(a)
        const numberB = Number(b)
        const comparison = a !== '' && b !== '' && Number.isFinite(numberA) && Number.isFinite(numberB)
          ? numberA - numberB
          : String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' })
        return sort.direction === 'asc' ? comparison : -comparison
      })
    }
    return result
  }, [records, search, sort])

  if (authInitializing) return <main className="auth-screen"><div className="loading-state"><span className="spinner" />Restoring your ARES session…</div></main>
  if (!auth) return <LoginScreen error={authError} saving={authSaving} onLogin={signIn} />

  const lastUpdatedLabel = formatRelativeTime(lastUpdated, clockNow)
  const apiConnected = apiHealth?.status === 'ok' && refreshState !== 'stale'

  const action = section === 'imports'
    ? { label: 'Import CSV', icon: '＋', modal: 'csv-import' }
    : section === 'response-plans'
      ? { label: 'New response plan', icon: '＋', modal: 'response-plan-create' }
    : section === 'inventory'
      ? { label: 'Record movement', icon: '＋', modal: 'movement' }
      : section === 'purchase-orders'
        ? { label: 'New purchase order', icon: '＋', modal: 'purchase-order' }
        : section === 'overview' || section === 'disruptions'
          ? { label: 'New disruption', icon: '＋', modal: 'disruption' }
          : null

  function toggleSort(key) {
    setSort((currentSort) => ({
      key,
      direction: currentSort.key === key && currentSort.direction === 'asc' ? 'desc' : 'asc',
    }))
  }

  function exportCsv() {
    const exportColumns = columns.filter(([key]) => !['assess', 'manage_plan'].includes(key))
    const rows = [exportColumns.map(([, title]) => title)]
    visibleRecords.forEach((record) => {
      rows.push(exportColumns.map(([key]) => {
        const value = key === 'line_count' ? record.lines?.length : record[key]
        const text = value && typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')
        return /^[=+\-@]/.test(text) ? `'${text}` : text
      }))
    })
    const csv = rows.map((row) => row.map((cell) => `"${String(cell).replaceAll('"', '""')}"`).join(',')).join('\r\n')
    const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `ares-${section}-${new Date().toISOString().slice(0, 10)}.csv`
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#overview" onClick={(event) => { event.preventDefault(); navigate('overview') }}>
          <span className="brand-mark">A</span>
          <span className="brand-copy"><strong>ARES</strong><small>SUPPLY CHAIN INTELLIGENCE</small></span>
        </a>
        <div className="workspace-pill"><span className="workspace-dot" /> <span>DEMO NETWORK</span><span className="workspace-chevron">⌄</span></div>
        <nav className="navigation" aria-label="Main navigation">
          <button
            aria-current={section === 'overview' ? 'page' : undefined}
            className={`nav-item nav-overview ${section === 'overview' ? 'selected' : ''}`}
            onClick={() => navigate('overview')}
            title="Overview"
          >
            <span className="nav-icon" aria-hidden="true">◫</span>
            <span>Overview</span>
          </button>
          {NAV_GROUPS.map((group) => {
            const expanded = expandedNavGroup === group.title
            const hasActiveItem = group.items.some(([key]) => key === section)
            const groupId = `nav-group-${group.title.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`
            return <div className={`nav-group ${expanded ? 'is-expanded' : ''} ${hasActiveItem ? 'has-active' : ''}`} key={group.title}>
              <button
                aria-controls={groupId}
                aria-expanded={expanded}
                className="nav-group-toggle"
                onClick={() => setExpandedNavGroup(expanded ? '' : group.title)}
                type="button"
              >
                <span className="nav-group-active-dot" aria-hidden="true" />
                <span className="nav-group-title">{group.title}</span>
                <span className="nav-group-chevron" aria-hidden="true">⌄</span>
              </button>
              <div className="nav-group-items" id={groupId} hidden={!expanded}>
                {group.items.map(([key, title, icon]) => (
                  <button
                    aria-current={section === key ? 'page' : undefined}
                    className={`nav-item ${section === key ? 'selected' : ''}`}
                    key={key}
                    onClick={() => navigate(key)}
                    title={title}
                  >
                    <span className="nav-icon" aria-hidden="true">{icon}</span>
                    <span>{title}</span>
                    {key === 'disruptions' && overview?.open_disruptions > 0 && <span className="nav-count">{overview.open_disruptions}</span>}
                  </button>
                ))}
              </div>
            </div>
          })}
        </nav>
        <div className="sidebar-bottom">
          <span className={`connection-light ${apiConnected ? 'is-online' : ''}`} />
          <span className="connection-copy"><strong>{apiConnected ? 'API connected' : refreshState === 'stale' ? 'Data refresh delayed' : 'API connection'}</strong><small>{apiHealth?.database || 'Waiting for backend'}</small></span>
          <span className="api-tag">LOCAL</span>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb"><span>ARES</span><i>/</i><strong>{current.title}</strong></div>
          <div className="topbar-actions">
            <span className={`api-status ${apiConnected ? 'connected' : refreshState === 'stale' ? 'stale' : ''}`}><i />{apiConnected ? 'API connected' : refreshState === 'stale' ? 'Update delayed' : 'Connecting'}</span>
            <button className={`icon-button refresh-button ${loading ? 'is-refreshing' : ''}`} aria-label="Refresh dashboard now" title="Refresh dashboard now" onClick={() => refresh()} disabled={loading}>↻</button>
            <span className="signed-in-name">{auth.display_name || auth.username}</span>
            <div className="avatar" aria-label={`Signed in as ${auth.display_name || auth.username}`}>{(auth.display_name || auth.username).split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase()}</div>
            <button className="secondary-button sign-out-button" onClick={signOut}>Sign out</button>
          </div>
        </header>

        <section className="page-content">
          <div className="page-heading">
            <div>
              <p className="eyebrow">AUTONOMOUS RESILIENT ENTERPRISE SUPPLY CHAIN</p>
              <h1>{current.title}</h1>
              <p className="page-description">{current.description}</p>
            </div>
            <div className="heading-actions">
              <div className={`updated-chip ${refreshState === 'stale' ? 'is-stale' : ''}`} title={`Dashboard changes arrive over an authenticated live connection when available, with a 30-second polling fallback. Last successful update: ${lastUpdatedLabel}.`}>
                <span className="pulse-dot" />
                <span>{refreshState === 'stale' ? 'Update delayed' : loading ? 'Refreshing' : liveUpdates === 'connected' ? 'Live updates' : '30-sec refresh'}</span>
                <small>{lastUpdated ? `· ${lastUpdatedLabel}` : '· waiting for data'}</small>
              </div>
              {action && <button className="primary-button" onClick={() => setModal(action.modal)}><span aria-hidden="true">{action.icon}</span>{action.label}</button>}
            </div>
          </div>

          {error && <div className="feedback-banner error-banner" role="alert"><span className="feedback-icon">!</span><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError('')}>×</button></div>}
          {notice && <div className="feedback-banner success-banner" role="status"><span className="feedback-icon">✓</span><span>{notice}</span><button aria-label="Dismiss notification" onClick={() => setNotice('')}>×</button></div>}

          {section === 'overview'
            ? <OverviewPage data={overview} homeData={homeData} loading={loading} apiHealth={apiHealth} refreshState={refreshState} lastUpdatedLabel={lastUpdatedLabel} onNavigate={navigate} onAssess={assessRisk} busyId={busyId} />
            : section === 'risk-intelligence'
              ? <RiskIntelligencePage data={riskData} loading={loading} canReview={Boolean(auth.is_approver)} onSubmitOutcome={saveRiskOutcome} onVerifyDelivery={verifyShipmentDelivery} savingId={busyId} />
            : <section className="panel records-panel">
              <div className="records-heading">
                <div><h2>{current.title}</h2><p>{records.length} {records.length === 1 ? 'record' : 'records'} in the local dataset</p></div>
                {loading && <span className="loading-inline"><i />Refreshing</span>}
              </div>
              {section === 'imports' && <ExternalFeedStatus source={feedStatus} />}
              {loading && records.length === 0
                ? <LoadingState />
                : <DataTable
                  section={section}
                  columns={columns}
                  records={visibleRecords}
                  total={records.length}
                  search={search}
                  onSearch={setSearch}
                  sort={sort}
                  onSort={toggleSort}
                  onExport={exportCsv}
                  onAssess={assessRisk}
                  onManagePlan={setSelectedPlan}
                  busyId={busyId}
                />}
            </section>}

          <footer className="page-footer"><span>ARES · LOCAL HACKFEST DEMO</span><span>Recommendations are advisory and require human review.</span></footer>
        </section>
      </main>

      {modal === 'disruption' && <DisruptionForm onClose={() => setModal('')} onSubmit={createDisruption} saving={saving} />}
      {modal === 'movement' && <MovementForm onClose={() => setModal('')} onSubmit={recordMovement} saving={saving} />}
      {modal === 'purchase-order' && <PurchaseOrderForm onClose={() => setModal('')} onSubmit={createPurchaseOrder} saving={saving} />}
      {modal === 'csv-import' && <ImportDialog onClose={() => setModal('')} onCommitted={completeImport} />}
      {modal === 'response-plan-create' && <ResponsePlanDialog currentUser={auth} onClose={() => setModal('')} onCreated={responsePlanCreated} />}
      {selectedPlan && <ResponsePlanDialog planId={selectedPlan} currentUser={auth} onClose={() => setSelectedPlan(null)} onChanged={responsePlanChanged} />}
      {assessment && <AssessmentModal result={assessment} onClose={() => setAssessment(null)} onMarkReviewed={markReviewed} />}
    </div>
  )
}

export default App
