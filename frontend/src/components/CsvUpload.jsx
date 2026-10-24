import { useState } from 'react'
import { demoUploadHandler } from './csvUploadHandler'

function formatFileSize(size) {
  if (size < 1024) {
    return `${size} bytes`
  }

  return `${(size / 1024).toLocaleString(undefined, {
    maximumFractionDigits: 2
  })} KB`
}

function CsvUpload({ uploadHandler = demoUploadHandler }) {
  const [selectedFile, setSelectedFile] = useState(null)
  const [validationError, setValidationError] = useState('')
  const [status, setStatus] = useState('idle')
  const [statusMessage, setStatusMessage] = useState('')

  function handleFileSelection(event) {
    const file = event.target.files?.[0] ?? null
    setSelectedFile(file)
    setStatus('idle')
    setStatusMessage('')

    if (!file) {
      setValidationError('')
      return
    }

    if (!file.name.toLowerCase().endsWith('.csv')) {
      setValidationError('Select a file with the .csv extension.')
      return
    }

    if (file.size === 0) {
      setValidationError('The selected CSV file is empty.')
      return
    }

    setValidationError('')
  }

  async function handleSubmit(event) {
    event.preventDefault()

    if (!selectedFile || validationError || status === 'loading') {
      return
    }

    setStatus('loading')
    setStatusMessage('Running the local demo check...')

    try {
      const result = await uploadHandler(selectedFile)
      setStatus('success')
      setStatusMessage(result.message)
    } catch (error) {
      setStatus('error')
      setStatusMessage(
        error instanceof Error
          ? `The demo could not complete: ${error.message}`
          : 'The demo could not complete because of an unexpected error.'
      )
    }
  }

  const canUpload = Boolean(selectedFile) && !validationError && status !== 'loading'

  return (
    <section>
      <h1>Upload ESG Data</h1>
      <p className="subtitle">
        Select a non-empty CSV file to check it in the local demo.
      </p>

      <div className="info-box csv-upload-card">
        <h3>CSV Upload</h3>
        <p>
          <strong>Demo mode:</strong> This interface does not send your file to
          a server. A backend upload API has not been configured.
        </p>

        <form onSubmit={handleSubmit}>
          <label className="csv-file-label" htmlFor="csv-file">
            Choose a CSV file
          </label>
          <input
            className="csv-file-input"
            id="csv-file"
            type="file"
            accept=".csv,text/csv"
            onChange={handleFileSelection}
            aria-describedby="csv-file-help"
          />
          <p className="csv-file-help" id="csv-file-help">
            CSV files only. Empty files are not accepted.
          </p>

          {selectedFile && (
            <div className="csv-file-details">
              <span className="csv-file-name">{selectedFile.name}</span>
              <span>{formatFileSize(selectedFile.size)}</span>
            </div>
          )}

          {validationError && (
            <p className="csv-status csv-status-error" role="alert">
              {validationError}
            </p>
          )}

          <button className="csv-upload-button" type="submit" disabled={!canUpload}>
            {status === 'loading' ? 'Checking...' : 'Upload'}
          </button>
        </form>

        {statusMessage && (
          <p
            className={`csv-status csv-status-${status}`}
            role={status === 'error' ? 'alert' : 'status'}
            aria-live="polite"
          >
            {statusMessage}
          </p>
        )}
      </div>
    </section>
  )
}

export default CsvUpload
