import PropertyComparison from './components/PropertyComparison'
import CsvUpload from './components/CsvUpload'
import EntitySelector from './components/EntitySelector'
import {
  getDefaultReportingYear,
  getReportingYears
} from './components/entityUtils'
import { useState, useEffect, useRef, useCallback } from 'react'
import './App.css'

import { API_BASE_URL, classifyApiError } from './api'
import { authenticatedFetch } from './auth'

function App() {
  // Remember which page the user selected
  const [currentPage, setCurrentPage] = useState('dashboard')


  const [entities, setEntities] = useState([])
  const [entitiesLoading, setEntitiesLoading] = useState(true)
  const [entitiesError, setEntitiesError] = useState(null)
  const [selectedEntity, setSelectedEntity] = useState('')
  const [selectedYear, setSelectedYear] = useState('')
  const loadEntitiesRef = useRef(null)

  const loadEntities = useCallback(async () => {
    const controller = new AbortController()
    loadEntitiesRef.current = controller

    try {
      setEntitiesLoading(true)
      setEntitiesError(null)

      const response = await authenticatedFetch(`${API_BASE_URL}/entities?scope=asset`, {
        signal: controller.signal
      })

      if (!response.ok) {
        throw new Error(`Entities API returned HTTP ${response.status}`)
      }

      const data = await response.json()
      if (
        !Array.isArray(data?.entities) ||
        data.entities.some(
          (entity) =>
            !entity ||
            typeof entity.entity_id !== 'string' ||
            entity.entity_id.trim() === ''
        )
      ) {
        throw new Error('Entities API returned an invalid entity list')
      }

      if (!controller.signal.aborted) {
        setEntities(data.entities)
        const firstEntity = data.entities[0]
        setSelectedEntity(firstEntity?.entity_id ?? '')
        setSelectedYear(getDefaultReportingYear(firstEntity))
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        const { type, message } = classifyApiError(error, 'Unable to retrieve properties.')
        setEntitiesError({ type, message })
      }
    } finally {
      if (!controller.signal.aborted) {
        setEntitiesLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    // This initial fetch intentionally starts from the effect lifecycle; the request is
    // aborted on cleanup and all state updates are isolated behind the async loader.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadEntities()

    return () => {
      loadEntitiesRef.current?.abort()
    }
  }, [loadEntities])

  // Retrieve ESG analytics data from the Python Analytics API
  const [analyticsResult, setAnalyticsResult] = useState(null)
  const selectedEntityDetails = entities.find(
    (entity) => entity.entity_id === selectedEntity
  )
  const selectedReportingYears = getReportingYears(selectedEntityDetails)
  const analyticsRequestKey = JSON.stringify([selectedEntity, selectedYear])
  const hasAnalyticsSelection =
    !entitiesLoading &&
    !entitiesError &&
    selectedEntityDetails &&
    selectedReportingYears.includes(selectedYear)
  const currentAnalyticsResult =
    analyticsResult?.key === analyticsRequestKey ? analyticsResult : null
  const analyticsData = currentAnalyticsResult?.data
  const analyticsError = currentAnalyticsResult?.error
  const analyticsLoading = Boolean(hasAnalyticsSelection && !currentAnalyticsResult)

  useEffect(() => {
    const entity = entities.find(
      (candidate) => candidate.entity_id === selectedEntity
    )
    const reportingYears = getReportingYears(entity)

    if (analyticsResult?.key === JSON.stringify([selectedEntity, selectedYear])) {
      return undefined
    }

    if (entitiesLoading || entitiesError || !entity || !reportingYears.includes(selectedYear)) {
      return undefined
    }

    const controller = new AbortController()
    const requestKey = JSON.stringify([selectedEntity, selectedYear])

    async function loadAnalytics() {
      try {
        const response = await authenticatedFetch(
          `${API_BASE_URL}/analysis/${encodeURIComponent(selectedEntity)}?scope=asset&reporting_year=${encodeURIComponent(selectedYear)}`,
          { signal: controller.signal }
        )


        if (!response.ok) {
          throw new Error(
            `Analytics API returned HTTP ${response.status}`
          )
        }

        const data = await response.json()
        if (!controller.signal.aborted) {
          setAnalyticsResult({ key: requestKey, data, error: null })
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setAnalyticsResult({
            key: requestKey,
            data: null,
            error: error.message
          })
        }
      }
    }

    loadAnalytics()

    return () => controller.abort()
  }, [
    analyticsResult?.key,
    entities,
    entitiesError,
    entitiesLoading,
    selectedEntity,
    selectedYear,
  ])

  function selectDashboardEntity(entityId) {
    const entity = entities.find(
      (candidate) => candidate.entity_id === entityId
    )
    setSelectedEntity(entityId)
    setSelectedYear(getDefaultReportingYear(entity))
  }

  // Find the energy intensity metric in the API response
  const energyMetric = analyticsData?.metrics?.find(
    (metric) => metric.metric_code === 'ENERGY_INTENSITY_EUI'
  )


  return (
    <div className="app">

      {/* Navigation bar */}
      <header className="navbar">
        <h2>🌱 ESG Benchmarking</h2>

        <nav>
          <button
            className={currentPage === 'dashboard' ? 'active' : ''}
            onClick={() => setCurrentPage('dashboard')}
          >
            Dashboard
          </button>

          <button
            className={currentPage === 'upload' ? 'active' : ''}
            onClick={() => setCurrentPage('upload')}
          >
            Upload Data
          </button>

          <button
            className={currentPage === 'comparison' ? 'active' : ''}
            onClick={() => setCurrentPage('comparison')}
          >
            Comparison
          </button>
        </nav>
      </header>

      {/* Main content */}
      <main className="main-content">

 
        {currentPage === 'dashboard' && (
          <section>
            <h1>Property ESG Dashboard</h1>

            {/* Property and reporting year selectors */}
            <div className="comparison-selectors dashboard-selectors">

              <div>
                <EntitySelector
                  id="selectedEntity"
                  label="Select Property"
                  entities={entities}
                  value={selectedEntity}
                  onChange={selectDashboardEntity}
                  disabled={entitiesLoading || Boolean(entitiesError)}
                  loading={entitiesLoading}
                />
              </div>

              <div>
                <label htmlFor="selectedYear">
                  Reporting Year
                </label>

                <select
                  id="selectedYear"
                  value={selectedYear}
                  onChange={(event) => setSelectedYear(event.target.value)}
                  disabled={
                    entitiesLoading ||
                    Boolean(entitiesError) ||
                    selectedReportingYears.length === 0
                  }
                >
                  {selectedReportingYears.length === 0 && (
                    <option value="">No reporting years available</option>
                  )}
                  {selectedReportingYears.map((year) => (
                    <option key={year} value={year}>{year}</option>
                  ))}
                </select>
              </div>

            </div>

            {entitiesLoading && (
              <div className="info-box" role="status">
                Loading available properties...
              </div>
            )}

            {entitiesError && (
              <div className="info-box">
                <p className="api-error">
                  {entitiesError.message}
                </p>
                {entitiesError.type === 'auth' ? (
                  <p>Please sign in and retry.</p>
                ) : (
                  <p>Please check that the Python Analytics API is running on port 8000.</p>
                )}
              </div>
            )}

            {!entitiesLoading && !entitiesError && entities.length === 0 && (
              <div className="info-box">
                The Analytics API did not return any properties.
              </div>
            )}

            {!entitiesLoading &&
              !entitiesError &&
              selectedEntityDetails &&
              selectedReportingYears.length === 0 && (
                <div className="info-box">
                  No reporting years are available for this property.
                </div>
              )}


            {analyticsLoading && (
              <div className="info-box">
                <p>Loading ESG analytics...</p>
              </div>
            )}

            {analyticsError && (
              <div className="info-box">
                <p className="api-error">
                  Unable to retrieve analytics: {analyticsError}
                </p>
                <p>
                  Please check that the Python Analytics API
                  is running on port 8000.
                </p>
              </div>
            )}

            {!analyticsLoading && !analyticsError && analyticsData && (
              <>
                <p className="subtitle">
                  {analyticsData.entity_name || selectedEntity}
                  {' '}({analyticsData.entity_id || selectedEntity}) |
                  Reporting Year: {analyticsData.reporting_year}
                </p>

                <div className="metric-grid">
                  <div className="metric-card">
                    <p>Energy Intensity</p>
                    <h2>
                      {energyMetric?.standardised_value ?? 'N/A'}
                    </h2>
                    <span>
                      {energyMetric?.canonical_unit ?? ''}
                    </span>
                  </div>

                  <div className="metric-card">
                    <p>Peer Median</p>
                    <h2>
                      {energyMetric?.benchmark?.peer_median ?? 'N/A'}
                    </h2>
                    <span>
                      {energyMetric?.canonical_unit ?? ''}
                    </span>
                  </div>

                  <div className="metric-card">
                    <p>Empirical Percentile</p>
                    <h2>
                      {energyMetric?.benchmark?.empirical_percentile ?? 'N/A'}
                    </h2>
                    <span>100 = best performance</span>
                  </div>

                  <div className="metric-card">
                    <p>Performance Gap</p>
                    <h2>
                      {energyMetric?.gap_analysis?.is_flagged == null
                        ? 'N/A'
                        : energyMetric.gap_analysis.is_flagged
                          ? 'Flagged'
                          : 'Not Flagged'}
                    </h2>
                    <span>Based on analytics threshold</span>
                  </div>
                </div>

                {/* Peer cohort information */}
                <div className="info-box dashboard-section">
                  <h3>Peer Benchmarking Information</h3>

                  <p>
                    <strong>Property type:</strong>{' '}
                    {analyticsData.peer_cohort?.property_type ?? 'N/A'}
                  </p>

                  <p>
                    <strong>Region:</strong>{' '}
                    {analyticsData.peer_cohort?.region ?? 'N/A'}
                  </p>

                  <p>
                    <strong>Peer cohort size:</strong>{' '}
                    {analyticsData.peer_cohort?.sample_size_n ?? 'N/A'}
                  </p>

                  <p>
                    <strong>Fallback applied:</strong>{' '}
                    {analyticsData.peer_cohort?.fallback_applied
                      ? 'Yes'
                      : 'No'}
                  </p>

                  {analyticsData.peer_cohort?.fallback_applied && (
                    <p>
                      <strong>Fallback reason:</strong>{' '}
                      {analyticsData.peer_cohort?.fallback_reason
                        ?? 'Not specified'}
                    </p>
                  )}
                </div>

                {/* ESG metrics table */}
                <div className="info-box dashboard-section">
                  <h3>ESG Metrics Overview</h3>

                  <div className="table-wrapper">
                    <table className="comparison-table">
                      <thead>
                        <tr>
                          <th>ESG Metric</th>
                          <th>Value</th>
                          <th>Peer Median</th>
                          <th>Percentile (0-100)</th>
                          <th>Status</th>
                        </tr>
                      </thead>

                      <tbody>
                        {analyticsData.metrics.map((metric) => (
                          <tr key={metric.metric_code}>
                            <td>
                              {metric.metric_code
                                .replaceAll('_', ' ')}
                            </td>

                            <td>
                              {metric.standardised_value == null
                                ? 'Not reported'
                                : `${Number(metric.standardised_value)
                                    .toLocaleString(undefined, {
                                      maximumFractionDigits: 2
                                    })} ${metric.canonical_unit}`}
                            </td>

                            <td>
                              {metric.benchmark?.peer_median == null
                                ? 'N/A'
                                : Number(metric.benchmark.peer_median)
                                    .toLocaleString(undefined, {
                                      maximumFractionDigits: 2
                                    })}
                            </td>

                            <td>
                                {metric.benchmark?.empirical_percentile == null
                                 ? 'N/A'
                                  : Number(metric.benchmark.empirical_percentile)
                                    .toLocaleString(undefined, {
                                    maximumFractionDigits: 2
                                  })}
                            </td>

                            <td>
                              {metric.comparability_status
                                .replaceAll('_', ' ')}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Gap analysis */}
                <div className="info-box dashboard-section">
                  <h3>ESG Gap Analysis</h3>

                  {analyticsData.metrics.some(
                    (metric) => metric.gap_analysis?.is_flagged
                  ) ? (
                    <ul>
                      {analyticsData.metrics
                        .filter(
                          (metric) => metric.gap_analysis?.is_flagged
                        )
                        .map((metric) => (
                          <li key={metric.metric_code}>
                            <strong>
                              {metric.metric_code.replaceAll('_', ' ')}
                            </strong>
                            {' — '}
                            {metric.gap_analysis?.gap_type
                              ?.replaceAll('_', ' ')}
                            <p>
                              {metric.gap_analysis?.recommendation_signal
                                ?? 'No recommendation available'}
                            </p>
                          </li>
                        ))}
                    </ul>
                  ) : (
                    <p>No ESG gaps flagged by the analytics engine.</p>
                  )}
                </div>
              </>
            )}
          </section>
        )}



        {currentPage === 'upload' && (
          <CsvUpload
            entities={entities}
            entitiesLoading={entitiesLoading}
            entitiesError={entitiesError}
            selectedEntity={selectedEntity}
            selectedYear={selectedYear}
            onRetryLoadEntities={loadEntities}
            onUploadSuccess={({ entityId, reportingYear, result }) => {
              const nextKey = JSON.stringify([entityId, String(reportingYear)])
              setSelectedEntity(entityId)
              setSelectedYear(String(reportingYear))
              setAnalyticsResult({ key: nextKey, data: result, error: null })
              setCurrentPage('dashboard')
            }}
          />
        )}

        
        {currentPage === 'comparison' && (
          <PropertyComparison
            entities={entities}
            entitiesLoading={entitiesLoading}
            entitiesError={entitiesError}
          />
        )}


      </main>

      <footer>
        CS5224 Group Project | ESG Benchmarking Platform
        <br />
        Prototype using fictional ESG data
      </footer>

    </div>
  )
}

export default App
