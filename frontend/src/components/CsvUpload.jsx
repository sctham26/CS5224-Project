import { useEffect, useRef, useState } from 'react'
import EntitySelector from './EntitySelector'
import { buildDefaultColumnMap, generateStandardisedCsv, makeMappedFile, parseCsvText, SPIP_REQUIRED_FIELDS } from './csvColumnMapper'
import { getDefaultReportingYear, getReportingYears } from './entityUtils'
import realCsvUploadHandler, { createIdempotencyKey } from './csvUploadHandler'

function formatFileSize(size) {
  if (size < 1024) {
    return `${size} bytes`
  }

  return `${(size / 1024).toLocaleString(undefined, {
    maximumFractionDigits: 2
  })} KB`
}

function resolveUploadTarget(entities, selectedEntity = '', selectedYear = '') {
  const entity = entities.find((candidate) => candidate.entity_id === selectedEntity) ?? null
  const availableYears = getReportingYears(entity)
  const effectiveYear = availableYears.includes(String(selectedYear))
    ? String(selectedYear)
    : getDefaultReportingYear(entity)

  return {
    entity,
    entityId: entity ? entity.entity_id : '',
    availableYears,
    effectiveYear: entity ? effectiveYear : '',
  }
}

function CsvUpload({
  uploadHandler = realCsvUploadHandler,
  entities = [],
  entitiesLoading = false,
  entitiesError = null,
  selectedEntity = '',
  selectedYear = '',
  onRetryLoadEntities,
  onUploadSuccess,
}) {
  const [selectedFile, setSelectedFile] = useState(null)
  const [validationError, setValidationError] = useState('')
  const [status, setStatus] = useState('idle')
  const [statusMessage, setStatusMessage] = useState('')
  const [mappingState, setMappingState] = useState({
    open: false,
    headers: [],
    sourceRows: [],
    mapping: {},
    previewRows: [],
    generatedCsv: '',
    generatedFile: null,
    error: '',
  })
  const [uploadEntityId, setUploadEntityId] = useState(() => {
    if (selectedEntity) return selectedEntity
    const firstEntity = entities[0]
    return firstEntity?.entity_id ?? ''
  })
  const [uploadYear, setUploadYear] = useState(() => {
    const initialEntity = entities.find((entity) => entity.entity_id === selectedEntity) ?? entities[0] ?? null
    const proposedYear = selectedYear && initialEntity
      ? getReportingYears(initialEntity).includes(String(selectedYear))
        ? String(selectedYear)
        : getDefaultReportingYear(initialEntity)
      : getDefaultReportingYear(initialEntity)

    return proposedYear
  })
  const idempotencyKeyRef = useRef('')
  const attemptRef = useRef({})

  useEffect(() => {
    if (selectedFile || ['reserving', 'uploading', 'queued', 'processing'].includes(status)) {
      return
    }

    const nextEntity = entities.find((entity) => entity.entity_id === selectedEntity) ?? null
    if (!nextEntity) {
      return
    }

    const nextYear = selectedYear && getReportingYears(nextEntity).includes(String(selectedYear))
      ? String(selectedYear)
      : getDefaultReportingYear(nextEntity)

    setUploadEntityId((currentEntityId) => (
      currentEntityId === nextEntity.entity_id ? currentEntityId : nextEntity.entity_id
    ))
    setUploadYear((currentYear) => (
      currentYear === nextYear ? currentYear : nextYear
    ))
  }, [entities, selectedEntity, selectedFile, selectedYear, status])

  const targetState = resolveUploadTarget(entities, uploadEntityId, uploadYear)
  const targetEntity = targetState.entity
  const availableYears = targetState.availableYears

  function handleEntitySelection(nextEntityId) {
    setUploadEntityId(nextEntityId)
    const nextEntity = entities.find((entity) => entity.entity_id === nextEntityId) ?? null
    const nextYear = getDefaultReportingYear(nextEntity)
    setUploadYear(nextYear)
  }

  function handleFileSelection(event) {
    const file = event.target.files?.[0] ?? null
    setSelectedFile(file)
    setStatus('idle')
    setStatusMessage('')
    setMappingState({
      open: false,
      headers: [],
      sourceRows: [],
      mapping: {},
      previewRows: [],
      generatedCsv: '',
      generatedFile: null,
      error: '',
    })

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

  async function handleOpenMapping() {
    if (!selectedFile) {
      return
    }

    try {
      const csvText = await selectedFile.text()
      const { headers, rows, parseErrors } = parseCsvText(csvText)

      if (!headers.length) {
        setMappingState({
          open: true,
          headers: [],
          sourceRows: [],
          mapping: {},
          previewRows: [],
          generatedCsv: '',
          generatedFile: null,
          error: 'The selected file does not contain a CSV header row.',
        })
        return
      }

      if (parseErrors.length > 0 && parseErrors.some((error) => error.code === 'TooFewFields' || error.code === 'TooManyFields')) {
        setMappingState({
          open: true,
          headers,
          sourceRows: rows,
          mapping: buildDefaultColumnMap(headers, {
            entityId: uploadEntityId,
            reportingYear: uploadYear,
            selectedEntity: targetEntity,
            scope: 'ASSET',
          }),
          previewRows: rows.slice(0, 5),
          generatedCsv: '',
          generatedFile: null,
          error: 'The CSV has parse issues. Review the mapped fields before upload.',
        })
        return
      }

      setMappingState({
        open: true,
        headers,
        sourceRows: rows,
        mapping: buildDefaultColumnMap(headers, {
          entityId: uploadEntityId,
          reportingYear: uploadYear,
          selectedEntity: targetEntity,
          scope: 'ASSET',
        }),
        previewRows: rows.slice(0, 5),
        generatedCsv: '',
        generatedFile: null,
        error: '',
      })
    } catch (error) {
      setMappingState({
        open: true,
        headers: [],
        sourceRows: [],
        mapping: {},
        previewRows: [],
        generatedCsv: '',
        generatedFile: null,
        error: error instanceof Error ? error.message : 'Unable to read the selected CSV file.',
      })
    }
  }

  function updateMappingSelection(field, header) {
    setMappingState((current) => {
      const nextMapping = { ...current.mapping }
      const fixedValue = field === 'entity_id'
        ? uploadEntityId
        : field === 'reporting_year'
          ? uploadYear
          : field === 'reporting_scope'
            ? 'ASSET'
            : field === 'property_type' && targetEntity?.property_type
              ? targetEntity.property_type
              : field === 'region' && targetEntity?.region
                ? targetEntity.region
                : ''

      if (header) {
        nextMapping[field] = { type: 'source', header }
      } else {
        nextMapping[field] = { type: 'fixed', value: fixedValue }
      }

      return { ...current, mapping: nextMapping }
    })
  }

  function handleGenerateMappedCsv() {
    try {
      const result = generateStandardisedCsv(mappingState.sourceRows, mappingState.mapping, {
        entityId: uploadEntityId,
        reportingYear: uploadYear,
        scope: 'ASSET',
        selectedEntity: targetEntity,
      })

      setMappingState((current) => ({
        ...current,
        previewRows: result.previewRows,
        generatedCsv: result.csvText,
        generatedFile: makeMappedFile(result.csvText, selectedFile?.name || 'mapped-upload.csv'),
        error: '',
      }))
    } catch (error) {
      setMappingState((current) => ({
        ...current,
        error: error instanceof Error ? error.message : 'The mapped CSV could not be validated.',
      }))
    }
  }

  function handleUseMappedCsv() {
    if (!mappingState.generatedFile) {
      return
    }

    setSelectedFile(mappingState.generatedFile)
    setValidationError('')
    setStatus('idle')
    setStatusMessage('Mapped CSV ready for upload.')
    setMappingState((current) => ({
      ...current,
      open: false,
    }))
  }

  async function handleSubmit(event) {
    event.preventDefault()

    if (!selectedFile || validationError || status === 'reserving' || status === 'uploading' || status === 'queued' || status === 'processing') {
      return
    }

    if (!uploadEntityId || !uploadYear || !targetEntity || !availableYears.includes(uploadYear)) {
      setStatus('failed')
      setStatusMessage('Choose a valid property and reporting year before uploading your CSV.')
      return
    }

    const identity = attemptRef.current
    if (identity.file !== selectedFile || identity.entityId !== uploadEntityId || identity.year !== uploadYear) {
      idempotencyKeyRef.current = ''
      attemptRef.current = { file: selectedFile, entityId: uploadEntityId, year: uploadYear }
    }
    const key = idempotencyKeyRef.current || createIdempotencyKey()
    idempotencyKeyRef.current = key

    try {
      const result = await uploadHandler(selectedFile, {
        entityId: uploadEntityId,
        reportingYear: uploadYear,
        idempotencyKey: key,
        attempt: attemptRef.current,
        onProgress: (nextStatus, message) => {
          setStatus(nextStatus)
          setStatusMessage(message)
        },
      })

      attemptRef.current = {}
      idempotencyKeyRef.current = ''
      setStatus('completed')
      setStatusMessage(result.message)
      onUploadSuccess?.({
        entityId: uploadEntityId,
        reportingYear: Number(uploadYear),
        result: result.result,
      })
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : 'The upload could not be completed because of an unexpected error.'

      setStatus(error.pending ? 'pending' : 'failed')
      setStatusMessage(message)
    }
  }

  const canUpload =
    Boolean(selectedFile) &&
    !validationError &&
    Boolean(uploadEntityId) &&
    Boolean(uploadYear) &&
    Boolean(targetEntity) &&
    availableYears.includes(uploadYear) &&
    !['reserving', 'uploading', 'queued', 'processing'].includes(status)

  const buttonLabel =
    status === 'reserving'
      ? 'Reserving...'
      : status === 'uploading'
        ? 'Uploading...'
        : status === 'queued'
          ? 'Queued...'
          : status === 'processing'
            ? 'Processing...'
            : status === 'completed'
              ? 'Completed'
              : 'Upload'

  const sourcePreview =
    mappingState.headers.length > 0
      ? `${mappingState.headers.join(',')}\n${mappingState.previewRows
          .slice(0, 5)
          .map((row) => Object.values(row).join(','))
          .join('\n')}`
      : ''

  const mappedPreview =
    mappingState.generatedCsv ? mappingState.generatedCsv.split('\n').slice(0, 7).join('\n') : ''

  return (
    <section>
      <h1>Upload ESG Data</h1>
      <p className="subtitle">
        Select a CSV file and submit it against the selected asset property and reporting year.
      </p>

      <div className="info-box csv-upload-card">
        <h3>CSV Upload</h3>

        {entitiesLoading && (
          <div className="info-box" role="status">
            Loading properties...
          </div>
        )}

        {!entitiesLoading && entitiesError && (
          <div className="info-box">
            <p className="api-error">{entitiesError.message}</p>
            {entitiesError.type === 'auth' ? (
              <p>Please sign in and retry.</p>
            ) : (
              <p>Check that the Python Analytics API is running on port 8000.</p>
            )}
            {onRetryLoadEntities && (
              <button type="button" onClick={onRetryLoadEntities}>
                Retry
              </button>
            )}
          </div>
        )}

        {!entitiesLoading && !entitiesError && (
          <>
            <p>
              <strong>Target:</strong>{' '}
              {targetEntity
                ? `${targetEntity.entity_name || targetEntity.entity_id} (${targetEntity.entity_id}) — ${uploadYear}`
                : 'No valid property/year selected'}
            </p>

            <div className="upload-target-selectors">
              <div className="upload-selector-block">
                <EntitySelector
                  id="upload-selected-entity"
                  label="Property"
                  entities={entities}
                  value={uploadEntityId}
                  onChange={handleEntitySelection}
                  disabled={entities.length === 0}
                  loading={entities.length === 0}
                />
              </div>

              <div className="upload-selector-block">
                <label htmlFor="upload-selected-year">Reporting Year</label>
                <select
                  id="upload-selected-year"
                  value={uploadYear}
                  onChange={(event) => setUploadYear(event.target.value)}
                  disabled={!targetEntity || availableYears.length === 0}
                >
                  {availableYears.length === 0 && (
                    <option value="">No reporting years available</option>
                  )}
                  {availableYears.map((year) => (
                    <option key={year} value={year}>{year}</option>
                  ))}
                </select>
              </div>
            </div>
          </>
        )}

        {!entitiesLoading && !entitiesError && (
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

          {selectedFile && !mappingState.open && (
            <button type="button" onClick={handleOpenMapping} className="csv-map-button" style={{ marginTop: '0.75rem' }}>
              Map CSV columns
            </button>
          )}

          {mappingState.open && (
            <div className="csv-file-details" style={{ display: 'block', marginTop: '1rem' }}>
              <h4>Map CSV columns</h4>
              <p>Map source fields to the SPIP long-format schema, or keep the fixed default values below.</p>

              <div style={{ display: 'grid', gap: '0.5rem', marginTop: '0.75rem' }}>
                {SPIP_REQUIRED_FIELDS.map((field) => {
                  const config = mappingState.mapping[field] || { type: 'fixed', value: '' }
                  const fixedValue = field === 'entity_id'
                    ? uploadEntityId
                    : field === 'reporting_year'
                      ? uploadYear
                      : field === 'reporting_scope'
                        ? 'ASSET'
                        : field === 'property_type' && targetEntity?.property_type
                          ? targetEntity.property_type
                          : field === 'region' && targetEntity?.region
                            ? targetEntity.region
                            : ''

                  return (
                    <div key={field} style={{ display: 'grid', gap: '0.25rem' }}>
                      <label htmlFor={`map-${field}`}>{field}</label>
                      <select
                        id={`map-${field}`}
                        value={config.type === 'source' ? config.header : '__fixed__'}
                        onChange={(event) => updateMappingSelection(field, event.target.value !== '__fixed__' ? event.target.value : '')}
                      >
                        <option value="__fixed__">Fixed value</option>
                        {mappingState.headers.map((header) => (
                          <option key={`${field}-${header}`} value={header}>{header}</option>
                        ))}
                      </select>

                      {config.type === 'fixed' && (
                        <input
                          type="text"
                          value={config.value || fixedValue}
                          onChange={(event) => {
                            const nextValue = event.target.value
                            setMappingState((current) => ({
                              ...current,
                              mapping: {
                                ...current.mapping,
                                [field]: { type: 'fixed', value: nextValue },
                              },
                            }))
                          }}
                        />
                      )}
                    </div>
                  )
                })}
              </div>

              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginTop: '1rem', flexWrap: 'wrap' }}>
                <button type="button" onClick={handleGenerateMappedCsv}>Preview mapped CSV</button>
              </div>

              {mappingState.error && (
                <p className="csv-status csv-status-error" role="alert" style={{ marginTop: '0.75rem' }}>
                  {mappingState.error}
                </p>
              )}

              {mappingState.generatedCsv && (
                <div style={{ marginTop: '1rem' }}>
                  <h5>Preview (first five rows)</h5>
                  <pre style={{ whiteSpace: 'pre-wrap', overflowX: 'auto', fontSize: '0.8rem' }}>
                    {mappedPreview}
                  </pre>
                  <button type="button" onClick={handleUseMappedCsv}>Use mapped CSV and continue</button>
                </div>
              )}

              {mappingState.headers.length > 0 && !mappingState.generatedCsv && (
                <div style={{ marginTop: '1rem' }}>
                  <h5>Source preview</h5>
                  <pre style={{ whiteSpace: 'pre-wrap', overflowX: 'auto', fontSize: '0.8rem' }}>
                    {sourcePreview}
                  </pre>
                </div>
              )}
            </div>
          )}

          {validationError && (
            <p className="csv-status csv-status-error" role="alert">
              {validationError}
            </p>
          )}

          {!uploadEntityId && (
            <p className="csv-status csv-status-error" role="alert">
              Select a valid property before uploading.
            </p>
          )}

          {!uploadYear && (
            <p className="csv-status csv-status-error" role="alert">
              Select a reporting year before uploading.
            </p>
          )}

          <button className="csv-upload-button" type="submit" disabled={!canUpload}>
            {buttonLabel}
          </button>
          </form>
        )}

        {!entitiesLoading && !entitiesError && statusMessage && (
          <p
            className={`csv-status csv-status-${status === 'failed' ? 'error' : status === 'completed' ? 'success' : status === 'idle' ? '' : status}`}
            role={status === 'failed' ? 'alert' : 'status'}
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
