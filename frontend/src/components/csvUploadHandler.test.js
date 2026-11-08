import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import CsvUpload from './CsvUpload'
import { authenticatedFetch } from '../auth'
import { realCsvUploadHandler } from './csvUploadHandler'

vi.mock('../auth', () => ({
  authenticatedFetch: vi.fn(),
}))

function renderComponent(ui) {
  const container = document.createElement('div')
  const root = createRoot(container)
  act(() => {
    root.render(ui)
  })
  return { container, root }
}

describe('realCsvUploadHandler', () => {
  const makeFile = () => new File(['entity_id,reporting_year\nA001,2024\n'], 'sample.csv', { type: 'text/csv' })

  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('uploads and only reports success after the job reaches SUCCEEDED', async () => {
    const apiFetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          upload_url: 'https://s3.example.invalid/upload',
          key: 'tenants/tenant_a/uploads/test.csv',
          content_type: 'text/csv',
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ job_id: 'job_123', status: 'QUEUED' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ job_id: 'job_123', status: 'SUCCEEDED', result: { entity_id: 'A001' } }),
      })

    const fetcher = vi.fn().mockResolvedValue({ ok: true })
    const onProgress = vi.fn()

    const result = await realCsvUploadHandler(makeFile(), {
      entityId: 'A001',
      reportingYear: 2024,
      idempotencyKey: 'job-key-1',
      apiFetch,
      fetcher,
      baseUrl: '/api',
      onProgress,
      pollIntervalMs: 1,
      timeoutMs: 100,
    })

    expect(result.status).toBe('SUCCEEDED')
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher.mock.calls[0][0]).toBe('https://s3.example.invalid/upload')
    expect(fetcher.mock.calls[0][1].headers['Content-Type']).toBe('text/csv')
    expect(fetcher.mock.calls[0][1].headers.Authorization).toBeUndefined()
    expect(apiFetch.mock.calls[1][1].headers['Idempotency-Key']).toBe('job-key-1')
    expect(JSON.parse(apiFetch.mock.calls[1][1].body)).toMatchObject({
      upload_key: 'tenants/tenant_a/uploads/test.csv',
      entity_id: 'A001',
      reporting_year: 2024,
      scope: 'asset',
    })

    const stages = onProgress.mock.calls.map(([stage]) => stage)
    expect(stages).toEqual(expect.arrayContaining(['reserving', 'uploading', 'queued', 'processing', 'completed']))
    expect(stages.indexOf('completed')).toBeGreaterThan(stages.indexOf('processing'))
  })

  it('reports an asynchronous backend failure with the backend error message', async () => {
    const apiFetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ upload_url: 'https://s3.example.invalid/upload', key: 'tenants/tenant_a/uploads/test.csv', content_type: 'text/csv' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ job_id: 'job_456', status: 'QUEUED' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ job_id: 'job_456', status: 'FAILED', error: 'CSV schema is invalid' }) })

    await expect(
      realCsvUploadHandler(makeFile(), {
        entityId: 'A001',
        reportingYear: 2024,
        idempotencyKey: 'fail-key',
        apiFetch,
        fetcher: vi.fn().mockResolvedValue({ ok: true }),
        baseUrl: '/api',
        pollIntervalMs: 1,
        timeoutMs: 100,
      })
    ).rejects.toThrow('CSV schema is invalid')
  })

  it('times out when the job never reaches a terminal state', async () => {
    const apiFetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ upload_url: 'https://s3.example.invalid/upload', key: 'tenants/tenant_a/uploads/test.csv', content_type: 'text/csv' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ job_id: 'job_timeout', status: 'QUEUED' }) })
      .mockResolvedValue({ ok: true, json: async () => ({ job_id: 'job_timeout', status: 'QUEUED' }) })

    await expect(
      realCsvUploadHandler(makeFile(), {
        entityId: 'A001',
        reportingYear: 2024,
        idempotencyKey: 'timeout-key',
        apiFetch,
        fetcher: vi.fn().mockResolvedValue({ ok: true }),
        baseUrl: '/api',
        pollIntervalMs: 1,
        timeoutMs: 20,
      })
    ).rejects.toThrow(/still pending/i)
  })

  it('prefers the backend 503 detail when the response includes a plain-text message', async () => {
    const apiFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      text: async () => JSON.stringify({ detail: 'Upload workers are restarting for maintenance.' }),
    })

    await expect(
      realCsvUploadHandler(makeFile(), {
        entityId: 'A001',
        reportingYear: 2024,
        idempotencyKey: '503-detail-key',
        apiFetch,
        fetcher: vi.fn().mockResolvedValue({ ok: true }),
        baseUrl: '/api',
      })
    ).rejects.toThrow('Upload workers are restarting for maintenance.')
  })

  it('prefers the backend 503 detail when the detail is a structured JSON object', async () => {
    const apiFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      text: async () =>
        JSON.stringify({
          detail: {
            message: 'Service queue is draining for maintenance',
            code: 'BACKEND_MAINTENANCE',
          },
        }),
    })

    await expect(
      realCsvUploadHandler(makeFile(), {
        entityId: 'A001',
        reportingYear: 2024,
        idempotencyKey: '503-structured-key',
        apiFetch,
        fetcher: vi.fn().mockResolvedValue({ ok: true }),
        baseUrl: '/api',
      })
    ).rejects.toThrow('Service queue is draining for maintenance')
  })

  it('falls back to a generic 503 message when the backend detail is missing or malformed', async () => {
    const missingDetail = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      text: async () => JSON.stringify({ detail: null }),
    })

    await expect(
      realCsvUploadHandler(makeFile(), {
        entityId: 'A001',
        reportingYear: 2024,
        idempotencyKey: '503-missing-key',
        apiFetch: missingDetail,
        fetcher: vi.fn().mockResolvedValue({ ok: true }),
        baseUrl: '/api',
      })
    ).rejects.toThrow(/The backend upload services are not configured or are temporarily unavailable\./i)

    const malformedDetail = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      text: async () => JSON.stringify({ detail: { stack: 'Traceback (most recent call last):\n...' } }),
    })

    await expect(
      realCsvUploadHandler(makeFile(), {
        entityId: 'A001',
        reportingYear: 2024,
        idempotencyKey: '503-malformed-key',
        apiFetch: malformedDetail,
        fetcher: vi.fn().mockResolvedValue({ ok: true }),
        baseUrl: '/api',
      })
    ).rejects.toThrow(/The backend upload services are not configured or are temporarily unavailable\./i)
  })

  it('turns a 401 response into an auth error', async () => {
    const apiFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => JSON.stringify({ detail: 'Token expired' }),
    })

    await expect(
      realCsvUploadHandler(makeFile(), {
        entityId: 'A001',
        reportingYear: 2024,
        idempotencyKey: 'auth-key',
        apiFetch,
        fetcher: vi.fn().mockResolvedValue({ ok: true }),
        baseUrl: '/api',
      })
    ).rejects.toThrow(/Authentication is required/i)
  })

  it('reuses the same idempotency key on retry', async () => {
    const apiFetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ upload_url: 'https://s3.example.invalid/upload', key: 'tenants/tenant_a/uploads/test.csv', content_type: 'text/csv' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ job_id: 'job_retry', status: 'QUEUED' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ job_id: 'job_retry', status: 'SUCCEEDED', result: { entity_id: 'A001' } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ upload_url: 'https://s3.example.invalid/upload', key: 'tenants/tenant_a/uploads/test.csv', content_type: 'text/csv' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ job_id: 'job_retry', status: 'QUEUED' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ job_id: 'job_retry', status: 'SUCCEEDED', result: { entity_id: 'A001' } }) })

    const upload = (key) =>
      realCsvUploadHandler(makeFile(), {
        entityId: 'A001',
        reportingYear: 2024,
        idempotencyKey: key,
        apiFetch,
        fetcher: vi.fn().mockResolvedValue({ ok: true }),
        baseUrl: '/api',
        pollIntervalMs: 1,
        timeoutMs: 100,
      })

    await upload('identical-key')
    await upload('identical-key')

    const jobHeaders = apiFetch.mock.calls
      .filter(([url]) => url === '/api/jobs')
      .map(([, options]) => options.headers['Idempotency-Key'])

    expect(jobHeaders).toEqual(['identical-key', 'identical-key'])
  })
})

describe('CsvUpload catalogue loading and recovery', () => {
  it('shows loading properties while the catalogue request is in flight', () => {
    const { container } = renderComponent(
      React.createElement(CsvUpload, {
        entities: [],
        entitiesLoading: true,
      })
    )

    expect(container.textContent).toContain('Loading properties...')
  })

  it('shows a clear retryable error when the catalogue request fails', () => {
    const onRetry = vi.fn()
    const { container } = renderComponent(
      React.createElement(CsvUpload, {
        entities: [],
        entitiesLoading: false,
        entitiesError: {
          type: 'network',
          message: 'The Python Analytics API is unavailable. Please check your connection and retry.',
        },
        onRetryLoadEntities: onRetry,
      })
    )

    expect(container.textContent).toContain('The Python Analytics API is unavailable')
    const retryButton = [...container.querySelectorAll('button')].find(
      (button) => button.textContent.trim() === 'Retry'
    )

    expect(retryButton).toBeTruthy()
    retryButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('preserves the selected file and upload progress when the catalogue refreshes mid-upload', async () => {
    const uploadHandler = vi.fn((file, { onProgress }) => {
      onProgress('uploading', 'Uploading...')
      return new Promise(() => {})
    })

    const entities = [
      { entity_id: 'A002', entity_name: 'Alpha Tower', reporting_years: [2024], latest_reporting_year: 2024 },
    ]
    const refreshedEntities = [
      { entity_id: 'A002', entity_name: 'Alpha Tower', reporting_years: [2024], latest_reporting_year: 2024 },
      { entity_id: 'B004', entity_name: 'Beta Tower', reporting_years: [2023], latest_reporting_year: 2023 },
    ]

    const { container, root } = renderComponent(
      React.createElement(CsvUpload, {
        entities,
        selectedEntity: 'A002',
        selectedYear: '2024',
        uploadHandler,
      })
    )

    const fileInput = container.querySelector('#csv-file')
    const file = new File(['a,b\n1,2\n'], 'upload.csv', { type: 'text/csv' })
    Object.defineProperty(fileInput, 'files', { value: [file], configurable: true })

    await act(async () => {
      fileInput.dispatchEvent(new Event('change', { bubbles: true }))
    })

    const form = container.querySelector('form')
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    })

    expect(container.textContent).toContain('Uploading...')
    expect(container.textContent).toContain('upload.csv')

    await act(async () => {
      root.render(
        React.createElement(CsvUpload, {
          entities: refreshedEntities,
          selectedEntity: 'A002',
          selectedYear: '2024',
          uploadHandler,
        })
      )
    })

    expect(uploadHandler).toHaveBeenCalledTimes(1)
    expect(container.textContent).toContain('Uploading...')
    expect(container.textContent).toContain('upload.csv')
    expect(container.querySelector('#upload-selected-year')).not.toBeNull()
  })
})

describe('App entity catalogue retry flow', () => {
  beforeEach(() => {
    vi.mocked(authenticatedFetch).mockReset()
  })

  it('retries GET /entities?scope=asset and recovers after a successful response', async () => {
    const fetchMock = vi.mocked(authenticatedFetch)
    fetchMock.mockRejectedValueOnce(new Error('Failed to fetch'))
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        entities: [{
          entity_id: 'A001',
          entity_name: 'Alpha Tower',
          property_type: 'Office',
          region: 'Singapore',
          postal_code: '123456',
          reporting_years: [2024],
          latest_reporting_year: 2024,
        }],
      }),
    })
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        entity_id: 'A001',
        entity_name: 'Alpha Tower',
        reporting_year: 2024,
        metrics: [],
      }),
    })

    const { container } = renderComponent(React.createElement(App))

    await act(async () => {
      await Promise.resolve()
    })

    expect(container.textContent).toContain('The Python Analytics API is unavailable')

    const uploadButton = [...container.querySelectorAll('button')].find(
      (button) => button.textContent.trim() === 'Upload Data'
    )
    expect(uploadButton).toBeTruthy()

    await act(async () => {
      uploadButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    const retryButton = [...container.querySelectorAll('button')].find(
      (button) => button.textContent.trim() === 'Retry'
    )
    expect(retryButton).toBeTruthy()

    await act(async () => {
      retryButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await Promise.resolve()
      await Promise.resolve()
      await Promise.resolve()
    })

    const entityCalls = fetchMock.mock.calls.filter(([url]) => url.includes('/entities?scope=asset'))
    expect(entityCalls).toHaveLength(2)
    expect(fetchMock.mock.calls[0][0]).toContain('/entities?scope=asset')
    expect(fetchMock.mock.calls[1][0]).toContain('/entities?scope=asset')
    expect(container.textContent).not.toContain('The Python Analytics API is unavailable')
    expect(container.textContent).toContain('Alpha Tower')
  })
})

describe('CsvUpload target selection', () => {
  const entities = [
    { entity_id: 'A002', entity_name: 'Alpha Tower', reporting_years: [2022, 2024], latest_reporting_year: 2024 },
    { entity_id: 'B004', entity_name: 'Beta Tower', reporting_years: [2023], latest_reporting_year: 2023 },
  ]

  it('shows the selected property and valid reporting years for the chosen target', () => {
    const { container } = renderComponent(
      React.createElement(CsvUpload, {
        entities,
        selectedEntity: 'A002',
        selectedYear: '2024',
      })
    )

    const targetText = container.textContent
    expect(targetText).toContain('Alpha Tower')
    expect(targetText).toContain('A002')
    expect(targetText).toContain('2024')

    const yearSelect = container.querySelector('#upload-selected-year')
    expect(yearSelect).not.toBeNull()
    expect([...yearSelect.options].map((option) => option.value)).toEqual(['2024', '2022'])
  })

  it('passes the selected entity and year back to App on successful upload', async () => {
    const onUploadSuccess = vi.fn()
    const uploadHandler = vi.fn().mockResolvedValue({
      message: 'CSV upload processed successfully.',
      result: { entity_id: 'A002', reporting_year: 2024, metrics: [] },
    })

    const { container } = renderComponent(
      React.createElement(CsvUpload, {
        entities,
        selectedEntity: 'A002',
        selectedYear: '2024',
        uploadHandler,
        onUploadSuccess,
      })
    )

    const fileInput = container.querySelector('#csv-file')
    const file = new File(['a,b\n1,2\n'], 'test.csv', { type: 'text/csv' })
    Object.defineProperty(fileInput, 'files', { value: [file], configurable: true })

    await act(async () => {
      fileInput.dispatchEvent(new Event('change', { bubbles: true }))
    })

    const button = container.querySelector('.csv-upload-button')
    expect(button.disabled).toBe(false)

    const form = container.querySelector('form')
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    })

    expect(uploadHandler).toHaveBeenCalledWith(file, expect.objectContaining({
      entityId: 'A002',
      reportingYear: '2024',
    }))
    expect(onUploadSuccess).toHaveBeenCalledWith({
      entityId: 'A002',
      reportingYear: 2024,
      result: { entity_id: 'A002', reporting_year: 2024, metrics: [] },
    })
  })

  it('refuses upload if the target property or year is invalid', async () => {
    const onUploadSuccess = vi.fn()
    const uploadHandler = vi.fn()

    const { container } = renderComponent(
      React.createElement(CsvUpload, {
        entities,
        selectedEntity: 'MISSING_PROPERTY',
        selectedYear: '9999',
        uploadHandler,
        onUploadSuccess,
      })
    )

    const fileInput = container.querySelector('#csv-file')
    const file = new File(['a,b\n1,2\n'], 'test.csv', { type: 'text/csv' })
    Object.defineProperty(fileInput, 'files', { value: [file], configurable: true })
    await act(async () => {
      fileInput.dispatchEvent(new Event('change', { bubbles: true }))
    })

    const button = container.querySelector('.csv-upload-button')
    expect(button.disabled).toBe(true)
    expect(uploadHandler).not.toHaveBeenCalled()
    expect(onUploadSuccess).not.toHaveBeenCalled()
  })
})

it('resumes an accepted job without another upload or submission', async () => {
  const apiFetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'SUCCEEDED', result: { entity_id: 'A001' } }) })
  const fetcher = vi.fn()
  const attempt = { uploadKey: 'tenants/a/uploads/existing.csv', job: { job_id: 'existing' } }
  const result = await realCsvUploadHandler(new File(['a'], 'a.csv'), {
    entityId: 'A001', reportingYear: 2024, attempt, apiFetch, fetcher, pollIntervalMs: 1,
  })
  expect(result.jobId).toBe('existing')
  expect(apiFetch).toHaveBeenCalledTimes(1)
  expect(apiFetch.mock.calls[0][0]).toMatch(/jobs\/existing$/)
  expect(fetcher).not.toHaveBeenCalled()
})
