import PropertyComparison from './components/PropertyComparison'
import CsvUpload from './components/CsvUpload'
import { useState, useEffect } from 'react'
import './App.css'


function App() {
  // Remember which page the user selected
  const [currentPage, setCurrentPage] = useState('dashboard')


  // Selected property and reporting year
  const [selectedEntity, setSelectedEntity] = useState('A001')
  const [selectedYear, setSelectedYear] = useState('2024')

  // Provisional property IDs for frontend testing
  const availableEntities = [
    'A001',
    'A002',
    'A003',
    'A004',
    'A005',
    'A006'
  ]


  // Retrieve ESG analytics data from the Python Analytics API
  const [analyticsData, setAnalyticsData] = useState(null)
  const [analyticsLoading, setAnalyticsLoading] = useState(true)
  const [analyticsError, setAnalyticsError] = useState(null)

  useEffect(() => {
    const controller = new AbortController()

    async function loadAnalytics() {
      try {
        setAnalyticsLoading(true)
        setAnalyticsData(null)
        setAnalyticsError(null)

        
        const response = await fetch(
          `http://localhost:8000/analysis/${encodeURIComponent(selectedEntity)}?scope=asset&reporting_year=${encodeURIComponent(selectedYear)}`,
          { signal: controller.signal }
        )


        if (!response.ok) {
          throw new Error(
            `Analytics API returned HTTP ${response.status}`
          )
        }

        const data = await response.json()
        setAnalyticsData(data)
      } catch (error) {
        if (error.name !== 'AbortError') {
          setAnalyticsError(error.message)
        }
      } finally {
        if (!controller.signal.aborted) {
          setAnalyticsLoading(false)
        }
      }
    }

    loadAnalytics()

    return () => controller.abort()
  }, [selectedEntity, selectedYear])

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
                <label htmlFor="selectedEntity">
                  Select Property
                </label>

                <select
                  id="selectedEntity"
                  value={selectedEntity}
                  onChange={(e) => setSelectedEntity(e.target.value)}
                >
                  {availableEntities.map((entityId) => (
                    <option key={entityId} value={entityId}>
                      {entityId}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label htmlFor="selectedYear">
                  Reporting Year
                </label>

                <select
                  id="selectedYear"
                  value={selectedYear}
                  onChange={(e) => setSelectedYear(e.target.value)}
                >
                  <option value="2024">2024</option>
                </select>
              </div>

            </div>


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
                  {analyticsData.entity_name} |
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
          <CsvUpload />
        )}

        
        {currentPage === 'comparison' && (
          <PropertyComparison />
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
