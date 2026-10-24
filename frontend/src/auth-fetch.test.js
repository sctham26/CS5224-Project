import { expect, it, vi } from 'vitest'
import { fetchWithAccessToken } from './auth-fetch'

it('sends the access token and preserves job idempotency and abort headers', async () => {
  const fetcher = vi.fn()
  const signal = new AbortController().signal
  await fetchWithAccessToken('/api/jobs', { method: 'POST', signal, headers: { 'Idempotency-Key': 'job-1' } },
    { baseUrl: '/api', origin: 'https://app.example', getToken: async () => 'access', fetcher })
  const options = fetcher.mock.calls[0][1]
  expect(options.headers.get('Authorization')).toBe('Bearer access')
  expect(options.headers.get('Idempotency-Key')).toBe('job-1')
  expect(options.signal).toBe(signal)
  expect(fetcher).toHaveBeenCalledTimes(1)
})

it.each(['https://s3.example/source', '/api-other/jobs', '//evil.example/api/jobs'])('does not leak tokens to %s', async url => {
  const getToken = vi.fn()
  const fetcher = vi.fn()
  await expect(fetchWithAccessToken(url, {}, { baseUrl: '/api', origin: 'https://app.example', getToken, fetcher })).rejects.toThrow('outside')
  expect(getToken).not.toHaveBeenCalled()
  expect(fetcher).not.toHaveBeenCalled()
})

it('does not call the API anonymously when a session is missing', async () => {
  const fetcher = vi.fn()
  await expect(fetchWithAccessToken('/api/jobs', {}, { baseUrl: '/api', origin: 'https://app.example',
    getToken: async () => { throw new Error('Sign in') }, fetcher })).rejects.toThrow('Sign in')
  expect(fetcher).not.toHaveBeenCalled()
})
