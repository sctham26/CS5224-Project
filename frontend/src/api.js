// Vite replaces this at build time. Never put credentials in frontend variables.
export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ||
  (import.meta.env.DEV ? 'http://localhost:8000' : '/api')
).replace(/\/+$/, '')

export function classifyApiError(error, fallbackMessage = 'The request could not be completed.') {
  const rawMessage =
    error instanceof Error
      ? error.message
      : typeof error === 'string'
        ? error
        : String(error ?? fallbackMessage)

  const message = rawMessage.trim() || fallbackMessage
  const lowerMessage = message.toLowerCase()

  if (
    /401|403|unauthorized|authentication|token expired|login is not configured/i.test(message)
  ) {
    return {
      type: 'auth',
      message: 'Authentication is required. Please sign in and retry.'
    }
  }

  if (
    /failed to fetch|network|offline|load failed|timeout|fetch failed|connection/i.test(lowerMessage)
  ) {
    return {
      type: 'network',
      message: 'The Python Analytics API is unavailable. Please check your connection and retry.'
    }
  }

  if (/http\s+\d+|api returned|entity.*api|unable to retrieve.*properties/i.test(message)) {
    return {
      type: 'api',
      message: message.includes('HTTP') || message.includes('API')
        ? message
        : `The Analytics API returned an error: ${message}`
    }
  }

  return {
    type: 'unknown',
    message
  }
}
