import { useState } from 'react'

export default function LoginScreen({ error, saving, onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  function submit(event) {
    event.preventDefault()
    onLogin({ username: username.trim(), password })
  }

  return <main className="auth-screen">
    <section className="auth-card" aria-labelledby="auth-title">
      <div className="auth-brand"><span className="brand-mark">A</span><span className="brand-copy"><strong>ARES</strong><small>SUPPLY CHAIN INTELLIGENCE</small></span></div>
      <p className="eyebrow">SECURE WORKSPACE</p>
      <h1 id="auth-title">Sign in to ARES</h1>
      <p className="auth-description">Use your ARES account to view supply-chain data and manage response work.</p>
      {error && <div className="form-error" role="alert">{error}</div>}
      <form onSubmit={submit}>
        <label className="form-field"><span className="field-label">Username</span><input autoComplete="username" required maxLength={150} value={username} onChange={(event) => setUsername(event.target.value)} /></label>
        <label className="form-field"><span className="field-label">Password</span><input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
        <button type="submit" className="primary-button auth-submit" disabled={saving || !username.trim() || !password}>{saving ? 'Signing in…' : 'Sign in'}</button>
      </form>
      <p className="auth-footnote">Accounts are provisioned by an ARES administrator.</p>
    </section>
  </main>
}
