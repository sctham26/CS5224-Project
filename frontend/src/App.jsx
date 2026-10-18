import { useState, useEffect } from 'react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer
} from 'recharts'
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


  // Fictional property data for frontend testing
  const properties = [
    {
      id: 'A',
      name: 'Building A',
      energy: 145,
      water: 0.85,
      carbon: 32
    },
    {
      id: 'B',
      name: 'Building B',
      energy: 190,
      water: 1.12,
      carbon: 41
    },
    {
      id: 'C',
      name: 'Building C',
      energy: 160,
      water: 0.94,
      carbon: 36
    }
  ]

  // Remember which properties the user selects
  const [property1, setProperty1] = useState('A')
  const [property2, setProperty2] = useState('B')

  // Find the selected properties
  const building1 = properties.find(
    (property) => property.id === property1
  )

  const building2 = properties.find(
    (property) => property.id === property2
  )

  // Calculate the absolute energy intensity difference
  const energyDifference = Math.abs(
    building1.energy - building2.energy
  )


  // Data used by the energy comparison chart
  const chartData = [
    {
      name: building1.name,
      energy: building1.energy
    },
    {
      name: building2.name,
      energy: building2.energy
    }
  ]


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
          <section>
            <h1>Upload ESG Data</h1>
            <p className="subtitle">
              Upload your property's ESG dataset for analysis.
            </p>

            <div className="info-box">
              <h3>CSV Upload</h3>
              <p>
                This page will allow users to upload
                ESG datasets in CSV format.
              </p>
              <p>File upload functionality coming soon.</p>
            </div>
          </section>
        )}

        {currentPage === 'comparison' && (
          <section>
            <h1>Property Comparison</h1>

            <p className="subtitle">
              Compare ESG performance across properties.
              All values are fictional demonstration data.
            </p>

            {/* Property selection */}
            <div className="comparison-selectors">

              <div>
                <label htmlFor="property1">
                  Property 1
                </label>

                <select
                  id="property1"
                  value={property1}
                  onChange={(e) => setProperty1(e.target.value)}
                >
                  {properties.map((property) => (
                    <option
                      key={property.id}
                      value={property.id}
                    >
                      {property.name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label htmlFor="property2">
                  Property 2
                </label>

                <select
                  id="property2"
                  value={property2}
                  onChange={(e) => setProperty2(e.target.value)}
                >
                  {properties.map((property) => (
                    <option
                      key={property.id}
                      value={property.id}
                    >
                      {property.name}
                    </option>
                  ))}
                </select>
              </div>

            </div>

            {property1 === property2 ? (
              <div className="info-box">
                <p>
                  Please select two different properties
                  to compare.
                </p>
              </div>
            ) : (
              <>
                {/* Comparison table */}
                <div className="info-box">
                  <h3>ESG Metrics Comparison</h3>

                  <div className="table-wrapper">
                    <table className="comparison-table">
                      <thead>
                        <tr>
                          <th>ESG Metric</th>
                          <th>{building1.name}</th>
                          <th>{building2.name}</th>
                        </tr>
                      </thead>

                      <tbody>
                        <tr>
                          <td>Energy Intensity (kWh/m²/year)</td>
                          <td>{building1.energy}</td>
                          <td>{building2.energy}</td>
                        </tr>

                        <tr>
                          <td>Water Intensity (m³/m²/year)</td>
                          <td>{building1.water}</td>
                          <td>{building2.water}</td>
                        </tr>

                        <tr>
                          <td>Carbon Intensity (kgCO₂e/m²/year)</td>
                          <td>{building1.carbon}</td>
                          <td>{building2.carbon}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Energy intensity bar chart */}
                <div className="info-box comparison-chart">
                  <h3>Energy Intensity Comparison</h3>

                  <p className="subtitle">
                    Lower energy intensity indicates
                    lower energy use per unit of floor area.
                  </p>

                  <div className="chart-container">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart
                        data={chartData}
                        margin={{
                          top: 20,
                          right: 20,
                          left: 10,
                          bottom: 10
                        }}
                      >
                        <CartesianGrid
                          strokeDasharray="3 3"
                        />

                        <XAxis dataKey="name" />

                        <YAxis
                          domain={[0, 'auto']}
                          label={{
                            value: 'kWh/m²/year',
                            angle: -90,
                            position: 'insideLeft'
                          }}
                        />

                        <Tooltip />

                        <Legend />

                        <Bar
                          dataKey="energy"
                          name="Energy Intensity"
                          fill="#40916c"
                          radius={[6, 6, 0, 0]}
                        />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                {/* Comparison summary */}
                <div className="info-box comparison-summary">
                  <h3>Energy Performance Comparison</h3>

                  <p>
                    Energy intensity difference:
                    <strong> {energyDifference} kWh/m²/year</strong>
                  </p>

                  
                  <p>
                    {building1.energy === building2.energy
                      ? 'Both properties have the same energy intensity.'
                      : building1.energy < building2.energy
                        ? `${building1.name} has lower energy intensity.`
                        : `${building2.name} has lower energy intensity.`}
                 </p>


                  <p className="comparison-note">
                    Note: This is a demonstration using
                    fictional properties. Real comparisons
                    will require validated comparable data.
                  </p>
                </div>
              </>
            )}
          </section>
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
