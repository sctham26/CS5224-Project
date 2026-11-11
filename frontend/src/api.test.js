import { describe, expect, it } from 'vitest'
import { classifyApiError } from './api'

describe('classifyApiError authentication responses', () => {
  it('gives HTTP 401 session recovery guidance', () => {
    expect(classifyApiError(new Error('Entities API returned HTTP 401'))).toEqual({
      type: 'auth',
      message: 'Your session could not be verified. Please sign out and sign in again.'
    })
  })

  it('gives HTTP 403 permission guidance', () => {
    expect(classifyApiError(new Error('Entities API returned HTTP 403'))).toEqual({
      type: 'forbidden',
      message: 'Your account does not have permission to access this data. Please contact your administrator.'
    })
  })
})
