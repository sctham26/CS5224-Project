// Attach credentials only to the configured application API, never to S3 or arbitrary URLs.
export async function fetchWithAccessToken(url, options, { baseUrl, origin, getToken, fetcher }) {
  const target = new URL(url, origin)
  const api = new URL(baseUrl, origin)
  const prefix = api.pathname.replace(/\/+$/, '')
  if (target.origin !== api.origin || !(target.pathname === prefix || target.pathname.startsWith(prefix + '/'))) {
    throw new Error('Refusing to send login credentials outside the configured API.')
  }
  const headers = new Headers(options.headers)
  headers.set('Authorization', 'Bearer ' + await getToken())
  return fetcher(url, { ...options, headers })
}
