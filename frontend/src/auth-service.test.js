import { describe, expect, it, vi } from 'vitest'
import { authSettings, createAuthService } from './auth-service'

function fixture(callback = false) {
  const handlers = {}
  const user = { access_token: 'access-only', refresh_token: 'refresh', expires_in: 900, profile: { sub: 'user-1' } }
  const manager = {
    events: {
      addUserLoaded: fn => { handlers.loaded = fn },
      addUserUnloaded: fn => { handlers.unloaded = fn },
      addAccessTokenExpired: fn => { handlers.expired = fn },
    },
    signinRedirectCallback: vi.fn().mockResolvedValue(user),
    getUser: vi.fn().mockResolvedValue(user),
    clearStaleState: vi.fn(), removeUser: vi.fn(), revokeTokens: vi.fn(),
    signinRedirect: vi.fn(), signinSilent: vi.fn().mockResolvedValue(user),
  }
  const browser = {
    location: { pathname: callback ? '/auth/callback' : '/', href: 'https://app.example/auth/callback?code=secret&state=bound', assign: vi.fn() },
    history: { replaceState: vi.fn() }, crypto: { randomUUID: () => 'random-nonce' },
  }
  const service = createAuthService(manager, { domain: 'https://login.example', clientId: 'public-client', origin: 'https://app.example' }, browser)
  return { service, manager, user, browser, handlers }
}

describe('login lifecycle', () => {
  it('exchanges a callback once under concurrent initialization and removes the code from the URL', async () => {
    const { service, manager, browser } = fixture(true)
    await Promise.all([service.initialize(), service.initialize()])
    expect(manager.signinRedirectCallback).toHaveBeenCalledTimes(1)
    expect(browser.history.replaceState).toHaveBeenCalledWith({}, '', '/')
    expect(await service.accessToken()).toBe('access-only')
  })
  it('rejects invalid callbacks without retaining a user or authorization code', async () => {
    const { service, manager, browser } = fixture(true)
    manager.signinRedirectCallback.mockRejectedValue(new Error('Invalid state'))
    await expect(service.initialize()).rejects.toThrow('Invalid state')
    expect(service.currentUser()).toBeNull()
    expect(browser.history.replaceState).toHaveBeenCalledWith({}, '', '/')
    await expect(service.accessToken()).rejects.toThrow('Sign in')
  })
  it('serializes refresh for concurrent API calls', async () => {
    const { service, manager, user } = fixture()
    user.expired = true
    await service.initialize()
    manager.signinSilent.mockResolvedValue({ ...user, expired: false, access_token: 'renewed-access' })
    expect(await Promise.all([service.accessToken(), service.accessToken()])).toEqual(['renewed-access', 'renewed-access'])
    expect(manager.signinSilent).toHaveBeenCalledTimes(1)
  })
  it('clears authentication when refresh fails instead of falling back to anonymous API calls', async () => {
    const { service, manager, user } = fixture()
    user.expired = true
    await service.initialize()
    manager.signinSilent.mockRejectedValue(new Error('revoked'))
    await expect(service.accessToken()).rejects.toThrow('session expired')
    expect(service.currentUser()).toBeNull()
    expect(manager.removeUser).toHaveBeenCalled()
  })
  it('revokes refresh tokens, clears local state and uses Cognito logout even if revocation fails', async () => {
    const { service, manager, browser } = fixture()
    await service.initialize()
    manager.revokeTokens.mockRejectedValue(new Error('network unavailable'))
    await service.signOut()
    expect(service.currentUser()).toBeNull()
    expect(manager.revokeTokens).toHaveBeenCalledWith(['refresh_token'])
    const logout = new URL(browser.location.assign.mock.calls[0][0])
    expect(logout.origin).toBe('https://login.example')
    expect(logout.searchParams.get('logout_uri')).toBe('https://app.example/')
    await expect(service.accessToken()).rejects.toThrow('Sign in')
  })
  it('adds an explicit nonce to login requests', async () => {
    const { service, manager } = fixture()
    await service.signIn()
    expect(manager.signinRedirect).toHaveBeenCalledWith({ nonce: 'random-nonce' })
  })
})

describe('configuration boundary', () => {
  it('allows demo only when explicitly selected in a development build', () => {
    expect(authSettings({ VITE_AUTH_MODE: 'demo' }, 'http://localhost:5173', true)).toBeNull()
    expect(() => authSettings({ VITE_AUTH_MODE: 'demo' }, 'https://app.example', false)).toThrow('local development')
    expect(() => authSettings({}, 'https://app.example', false)).toThrow('not configured')
  })
})
