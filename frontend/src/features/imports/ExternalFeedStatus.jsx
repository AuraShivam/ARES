function formatTime(value) {
  if (!value) return 'Not synced yet'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? 'Unknown'
    : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

const STATUS_LABELS = {
  syncing: 'Syncing',
  never: 'Waiting for first sync',
  ok: 'Healthy',
  partial: 'Partial sync',
  failed: 'Sync failed',
  configuration_error: 'Configuration error',
  configuration_changed: 'Configuration changed',
}

export default function ExternalFeedStatus({ source }) {
  if (!source) return null

  const status = STATUS_LABELS[source.status] || source.status
  const statusClass = ['ok', 'syncing'].includes(source.status) ? 'healthy' : ['failed', 'configuration_error'].includes(source.status) ? 'error' : 'pending'
  const intervalMinutes = Math.max(1, Math.round((source.poll_interval_seconds || 300) / 60))

  return <section className="feed-status-card" aria-labelledby="feed-status-heading">
    <div className="feed-status-main">
      <div>
        <p className="eyebrow">EXTERNAL DATA SOURCE</p>
        <h3 id="feed-status-heading">{source.name}</h3>
        <p className="feed-status-description">Recent global disaster alerts are normalized into advisory ARES disruption records.</p>
      </div>
      <span className={`feed-status-badge ${statusClass}`}><i />{status}</span>
    </div>
    <div className="feed-status-grid">
      <div><span>Minimum alert level</span><strong>{source.minimum_alert_level || 'orange'}</strong></div>
      <div><span>Polling interval</span><strong>Every {intervalMinutes} min</strong></div>
      <div><span>Last successful sync</span><strong>{formatTime(source.last_success_at)}</strong></div>
      <div><span>Recent feed events</span><strong>{source.recent_events ?? 0}</strong></div>
    </div>
    {source.last_error && <p className={`feed-status-message ${statusClass === 'error' ? 'error' : ''}`} role={statusClass === 'error' ? 'alert' : undefined}>{source.last_error}</p>}
    {source.status === 'configuration_changed' && <p className="feed-status-instructions">Restart the feed command to apply the new alert threshold or polling interval.</p>}
    {source.status !== 'configuration_changed' && <p className="feed-status-instructions">Start <code>python manage.py sync_gdacs_alerts --watch</code> from the backend directory to poll this feed.</p>}
  </section>
}
