import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CsvUpload from './CsvUpload'
import { realCsvUploadHandler } from './csvUploadHandler'

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
    ).rejects.toThrow(/timed out/i)
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
