import { useEffect, useState } from 'react'
import { auth, configurationError, demo } from './auth'

export default function AuthGate({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(!demo && !configurationError)
  const [error, setError] = useState(configurationError)
  useEffect(() => {
    if (!auth) return
    const unsubscribe = auth.subscribe(setUser)
    auth.initialize().then(setUser).catch(() => {
      setError('Login could not be completed. Please start a new sign-in.')
    }).finally(() => setLoading(false))
    return unsubscribe
  }, [])
  if (demo) return <><aside role="status">Local demo: authentication is disabled.</aside>{children}</>
  if (loading) return <main><p role="status">Completing sign-in…</p></main>
  if (!user) return (
    <main>
      <h1>Sign in to SPIP</h1>
      <p>Use your invited account to access the platform.</p>
      {error && <p role="alert">{error}</p>}
      <button disabled={!auth} onClick={() => auth.signIn().catch(() => setError('Unable to start sign-in. Please retry.'))}>Sign in</button>
    </main>
  )
  return (
    <>
      <aside aria-label="Account">
        <span>Signed in as {user.profile.email || user.profile.sub}</span>{' '}
        <button onClick={() => auth.signOut().catch(() => setError('Sign-out could not complete. Close this tab and retry.'))}>Sign out</button>
        {error && <p role="alert">{error}</p>}
      </aside>
      {children}
    </>
  )
}
