// Vite replaces this at build time. Never put credentials in frontend variables.
export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ||
  (import.meta.env.DEV ? 'http://localhost:8000' : '/api')
).replace(/\/+$/, '')
