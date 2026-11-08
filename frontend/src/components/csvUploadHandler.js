import { API_BASE_URL } from '../api'
import { authenticatedFetch } from '../auth'

export function createIdempotencyKey(prefix = 'spip-upload') {
  const suffix =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`

  return `${prefix}-${suffix}`
}

function normalizeErrorDetail(value) {
  if (typeof value === 'string') {
    const normalized = value.trim()
    if (!normalized) {
      return ''
    }

    if (/<[a-z!]/i.test(normalized) || /traceback|stack trace|stacktrace|exception/i.test(normalized)) {
      return ''
    }

    return normalized.replace(/\s+/g, ' ').slice(0, 500)
  }

  if (Array.isArray(value)) {
    for (const item of value) {
      const normalized = normalizeErrorDetail(item)
      if (normalized) {
        return normalized
      }
    }

    return ''
  }

  if (value && typeof value === 'object') {
    const preferredKeys = ['message', 'detail', 'error', 'title', 'description', 'reason']
    for (const key of preferredKeys) {
      const normalized = normalizeErrorDetail(value[key])
      if (normalized) {
        return normalized
      }
    }

    for (const [key, nestedValue] of Object.entries(value)) {
      if (/stack|traceback|html|body/.test(key.toLowerCase())) {
        continue
      }

      const normalized = normalizeErrorDetail(nestedValue)
      if (normalized) {
        return normalized
      }
    }
  }

  return ''
}

function getJsonErrorMessage(response, fallbackMessage) {
  if (!response || typeof response.status !== 'number') {
    return fallbackMessage
  }

  switch (response.status) {
    case 401:
      return 'Authentication is required or your session has expired.'
    case 403:
      return 'You are not allowed to upload data for this tenant.'
    case 404:
      return 'The requested upload resource is unavailable or not accessible.'
    case 409:
      return 'This upload request conflicts with an earlier idempotent retry. Reuse the same Idempotency-Key and request body.'
    case 503:
      return fallbackMessage || 'The backend upload services are not configured or are temporarily unavailable.'
    default:
      return fallbackMessage
  }
}

async function readErrorDetails(response, fallbackMessage) {
  let detail = ''

  try {
    const text = await response.text()
    if (text) {
      const parsed = JSON.parse(text)
      const candidate = parsed?.detail || parsed?.error || parsed?.message
      const normalized = normalizeErrorDetail(candidate)
      if (normalized) {
        detail = normalized
      }
    }
  } catch {
    // Response body may not be JSON; keep the status-aware fallback.
  }

  if (response.status === 503 && !detail) {
    return 'The backend upload services are not configured or are temporarily unavailable.'
  }

  return getJsonErrorMessage(response, detail || fallbackMessage)
}

export async function realCsvUploadHandler(
  file,
  {
    entityId,
    reportingYear,
    idempotencyKey,
    onProgress,
    pollIntervalMs = 1500,
    timeoutMs = 180000,
    attempt = {},
    apiFetch = authenticatedFetch,
    fetcher = fetch,
    baseUrl = API_BASE_URL,
  } = {}
) {
  if (!file) {
    throw new Error('Select a CSV file before uploading.')
  }

  if (!entityId || !reportingYear) {
    throw new Error('Select a valid property and reporting year before uploading.')
  }

  const resolvedIdempotencyKey = idempotencyKey || createIdempotencyKey()

  try {
    if (!attempt.uploadKey) {
    onProgress?.('reserving', 'Reserving upload space...')

    const reservationResponse = await apiFetch(`${baseUrl}/uploads`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })

    if (!reservationResponse.ok) {
      throw new Error(await readErrorDetails(reservationResponse, 'Failed to reserve an upload slot.'))
    }

    const reservation = await reservationResponse.json()
    if (!reservation?.upload_url || !reservation?.key) {
      throw new Error('The upload reservation did not include a valid presigned URL.')
    }

    onProgress?.('uploading', 'Uploading your CSV file to storage...')

    const putResponse = await fetcher(reservation.upload_url, {
      method: 'PUT',
      headers: { 'Content-Type': reservation.content_type || 'text/csv' },
      body: file,
    })

    if (!putResponse.ok) {
      throw new Error(
        'The CSV upload to storage failed or the presigned URL expired. Please try again.'
      )
    }

    attempt.uploadKey = reservation.key
    }

    const jobRequestBody = {
      upload_key: attempt.uploadKey,
      entity_id: entityId,
      reporting_year: Number(reportingYear),
      scope: 'asset',
    }

    onProgress?.('queued', 'Upload complete. Submitting the processing job...')

    let job = attempt.job
    if (!job) {
    const jobResponse = await apiFetch(`${baseUrl}/jobs`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': resolvedIdempotencyKey,
      },
      body: JSON.stringify(jobRequestBody),
    })

    if (!jobResponse.ok) {
      throw new Error(await readErrorDetails(jobResponse, 'The upload job could not be submitted.'))
    }

    job = await jobResponse.json()
    if (!job?.job_id) {
      throw new Error('The job submission did not return a valid job identifier.')
    }

    attempt.job = job
    }

    const startedAt = Date.now()
    onProgress?.('queued', 'Your CSV is queued for processing. Waiting for the result...')
    onProgress?.('processing', 'Processing your CSV file...')

    while (Date.now() - startedAt < timeoutMs) {
      await new Promise((resolve) => setTimeout(resolve, pollIntervalMs))

      const statusResponse = await apiFetch(`${baseUrl}/jobs/${encodeURIComponent(job.job_id)}`, {
        method: 'GET',
      })

      if (!statusResponse.ok) {
        throw new Error(await readErrorDetails(statusResponse, 'The job status could not be loaded.'))
      }

      const currentJob = await statusResponse.json()
      const currentStatus = currentJob?.status

      if (currentStatus === 'SUCCEEDED') {
        if (!currentJob?.result) {
          throw new Error('The job reached SUCCEEDED without a valid result payload.')
        }

        onProgress?.('completed', 'Upload processed successfully.')
        return {
          message: 'CSV upload processed successfully.',
          status: 'SUCCEEDED',
          jobId: job.job_id,
          result: currentJob.result,
        }
      }

      if (currentStatus === 'FAILED') {
        const errorMessage = currentJob?.error || 'The upload job failed asynchronously without a detailed backend error.'
        onProgress?.('failed', errorMessage)
        throw new Error(errorMessage)
      }

      onProgress?.('processing', 'Processing your CSV file...')
    }

    const error = new Error('Your job is still pending. Retry to continue checking the same job.')
    error.pending = true
    throw error
  } catch (error) {
    const message =
      error instanceof Error
        ? error.message
        : 'The CSV upload could not be completed because of an unexpected error.'

    onProgress?.(error.pending ? 'pending' : 'failed', message)
    throw error
  }
}

export default realCsvUploadHandler
