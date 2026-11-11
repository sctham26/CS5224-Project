import { InMemoryWebStorage, UserManager, WebStorageStateStore } from 'oidc-client-ts'
import { authSettings, createAuthService } from './auth-service'
import { API_BASE_URL } from './api'
import { fetchWithAccessToken } from './auth-fetch'

let auth = null
let configurationError = ''
let demo = false
try {
  const settings = authSettings(import.meta.env, window.location.origin, import.meta.env.DEV)
  demo = settings === null
  if (settings) {
    const manager = new UserManager({
      authority: settings.issuer,
      client_id: settings.clientId,
      redirect_uri: settings.origin + '/auth/callback',
      response_type: 'code',
      scope: 'openid email spip/access',
      loadUserInfo: false,
      automaticSilentRenew: false,
      monitorSession: false,
      revokeTokenTypes: ['refresh_token'],
      // OAuth transactions survive redirects; tokens never enter web storage.
      stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
      userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
      metadata: {
        issuer: settings.issuer,
        authorization_endpoint: settings.domain + '/oauth2/authorize',
        token_endpoint: settings.domain + '/oauth2/token',
        revocation_endpoint: settings.domain + '/oauth2/revoke',
        jwks_uri: settings.issuer + '/.well-known/jwks.json',
      },
    })
    auth = createAuthService(manager, settings, window)
  }
} catch (error) {
  configurationError = error.message
}

export { auth, configurationError, demo }

export async function authenticatedFetch(url, options = {}) {
  if (demo) return fetch(url, options)
  if (!auth) throw new Error(configurationError || 'Login is not configured.')
  // Never retry a POST automatically; backend owns idempotent job submission.
  return fetchWithAccessToken(url, options, { baseUrl: API_BASE_URL,
    origin: window.location.origin, getToken: auth.accessToken, fetcher: fetch })
}
