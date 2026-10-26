// Browser session orchestration; the OIDC library owns PKCE/state/nonce checks.
export function authSettings(env, origin, dev) {
  if (env.VITE_AUTH_MODE === 'demo') {
    if (!dev) throw new Error('Demo authentication is allowed only in local development.')
    return null
  }
  const issuer = env.VITE_AUTH_ISSUER
  const clientId = env.VITE_AUTH_CLIENT_ID
  const domain = env.VITE_AUTH_DOMAIN
  if (!issuer || !clientId || !domain) throw new Error('Login is not configured. Ask the cloud team to supply the public Cognito settings.')
  if (new URL(issuer).protocol !== 'https:' || new URL(domain).protocol !== 'https:') {
    throw new Error('Cognito endpoints must use HTTPS.')
  }
  return { issuer, clientId, domain: domain.replace(/\/+$/, ''), origin }
}

export function createAuthService(manager, settings, browser) {
  let user = null
  let initialization
  let refreshing
  let signingOut = false
  const subscribers = new Set()
  const notify = () => subscribers.forEach(fn => fn(user))
  const update = value => { user = value; notify() }
  manager.events.addUserLoaded(update)
  manager.events.addUserUnloaded(() => update(null))
  // Keep the shell mounted during refresh; failed refresh returns to login.
  manager.events.addAccessTokenExpired(() => {
    accessToken().catch(() => update(null))
  })
  async function accessToken() {
    if (signingOut || !user) throw new Error('Sign in to continue.')
    if (user.expired || user.expires_in < 60) {
      refreshing ??= manager.signinSilent().then(update).catch(async () => {
        await manager.removeUser()
        update(null)
        throw new Error('Your session expired. Sign in again.')
      }).finally(() => { refreshing = null })
      await refreshing
    }
    if (signingOut || !user?.access_token) throw new Error('Sign in to continue.')
    return user.access_token
  }
  return {
    subscribe(fn) { subscribers.add(fn); return () => subscribers.delete(fn) },
    currentUser: () => user,
    initialize() {
      // React StrictMode must not exchange a single-use callback code twice.
      initialization ??= (async () => {
        try {
          if (browser.location.pathname === '/auth/callback') {
            update(await manager.signinRedirectCallback(browser.location.href))
          } else {
            update(await manager.getUser())
          }
        } finally {
          if (browser.location.pathname === '/auth/callback') browser.history.replaceState({}, '', '/')
        }
        await manager.clearStaleState()
        return user
      })()
      return initialization
    },
    signIn: () => manager.signinRedirect({ nonce: browser.crypto.randomUUID() }),
    accessToken,
    async signOut() {
      signingOut = true
      // Cognito logout uses logout_uri, not the generic OIDC end-session URL.
      try { await manager.revokeTokens(['refresh_token']) } catch { /* Still clear local state and hosted cookie. */ }
      await manager.removeUser()
      update(null)
      const url = new URL(settings.domain + '/logout')
      url.searchParams.set('client_id', settings.clientId)
      url.searchParams.set('logout_uri', settings.origin + '/')
      browser.location.assign(url.href)
    },
  }
}
