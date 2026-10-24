
import { useEffect, useState } from 'react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer
} from 'recharts'

// Local analytics API used during development
const API_BASE_URL = 'http://localhost:8000'

// Temporary property list until a property-list API is available
const PROPERTY_IDS = [
  'A001',
  'A002',
  'A003',
  'A004',
  'A005',
  'A006'
]

const METRICS = [
  {
    code: 'ENERGY_INTENSITY_EUI',
    label: 'Energy Intensity'
  },
  {
    code: 'CARBON_INTENSITY_SCOPE2',
    label: 'Scope 2 Carbon Intensity'
  },
  {
    code: 'WATER_INTENSITY',
    label: 'Water Intensity'
  },
  {
    code: 'RENEWABLE_SHARE',
    label: 'Renewable Energy Share'
  },
  {
    code: 'WASTE_DIVERSION_RATE',
    label: 'Waste Diversion Rate'
  }
]

function getMetric(data, code) {
  return data?.metrics?.find(
    (metric) => metric.metric_code === code
  )
}

function isUsable(metric) {
  return (
    metric != null &&
    metric.standardised_value != null &&
    Number.isFinite(Number(metric.standardised_value)) &&
    ['COMPARABLE', 'UNIT_CONVERTED'].includes(
      metric.comparability_status
    )
  )
}

function formatNumber(value) {
  if (value == null) return 'N/A'

  return Number(value).toLocaleString(undefined, {
    maximumFractionDigits: 2
  })
}

function PropertyComparison() {
  const [property1, setProperty1] = useState('A001')
  const [property2, setProperty2] = useState('A002')
  const [reportingYear, setReportingYear] = useState('2024')
  const [selectedMetric, setSelectedMetric] = useState(
    'ENERGY_INTENSITY_EUI'
  )

  const [comparisonData, setComparisonData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (property1 === property2) {
      return
    }

    const controller = new AbortController()

    async function loadComparison() {
      setLoading(true)
      setError(null)
      setComparisonData(null)

      try {
        const fetchProperty = async (entityId) => {
          const response = await fetch(
            `${API_BASE_URL}/analysis/${encodeURIComponent(entityId)}` +
              `?scope=asset&reporting_year=${reportingYear}`,
            { signal: controller.signal }
          )

          if (!response.ok) {
            throw new Error(
              `Unable to load ${entityId} (HTTP ${response.status})`
            )
          }

          return response.json()
        }

        const [first, second] = await Promise.all([
          fetchProperty(property1),
          fetchProperty(property2)
        ])

        if (!controller.signal.aborted) {
          setComparisonData([first, second])
        }
      } catch (err) {
        if (!controller.signal.aborted) {
          setError(err.message)
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }

    loadComparison()

    return () => controller.abort()
  }, [property1, property2, reportingYear])

  const sameProperty = property1 === property2

  const first = comparisonData?.[0]
  const second = comparisonData?.[1]

  const firstMetric = getMetric(first, selectedMetric)
  const secondMetric = getMetric(second, selectedMetric)

  const comparable =
    isUsable(firstMetric) &&
    isUsable(secondMetric) &&
    firstMetric.canonical_unit === secondMetric.canonical_unit &&
    first?.reporting_year === second?.reporting_year &&
    firstMetric.performance_direction ===
      secondMetric.performance_direction

  const firstValue = Number(firstMetric?.standardised_value)
  const secondValue = Number(secondMetric?.standardised_value)

  const difference = comparable
    ? Math.abs(firstValue - secondValue)
    : null

  const chartData = comparable
    ? [
        {
          name: first.entity_name || first.entity_id,
          value: firstValue
        },
        {
          name: second.entity_name || second.entity_id,
          value: secondValue
        }
      ]
    : []

  return (
    <section>
      <h1>Property ESG Comparison</h1>

      <p className="subtitle">
        Compare standardised ESG metrics across properties.
        Results are retrieved from the Analytics API.
      </p>

      <div className="comparison-selectors">
        <div>
          <label htmlFor="compareProperty1">Property 1</label>
          <select
            id="compareProperty1"
            value={property1}
            onChange={(e) => setProperty1(e.target.value)}
          >
            {PROPERTY_IDS.map((id) => (
              <option key={id} value={id}>{id}</option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="compareProperty2">Property 2</label>
          <select
            id="compareProperty2"
            value={property2}
            onChange={(e) => setProperty2(e.target.value)}
          >
            {PROPERTY_IDS.map((id) => (
              <option key={id} value={id}>{id}</option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="compareYear">Reporting Year</label>
          <select
            id="compareYear"
            value={reportingYear}
            onChange={(e) => setReportingYear(e.target.value)}
          >
            <option value="2024">2024</option>
          </select>
        </div>

        <div>
          <label htmlFor="compareMetric">Chart Metric</label>
          <select
            id="compareMetric"
            value={selectedMetric}
            onChange={(e) => setSelectedMetric(e.target.value)}
          >
            {METRICS.map((metric) => (
              <option key={metric.code} value={metric.code}>
                {metric.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {sameProperty && (
        <div className="info-box">
          Please select two different properties.
        </div>
      )}

      {!sameProperty && loading && (
        <div className="info-box" role="status">
          Loading property comparison...
        </div>
      )}

      {!sameProperty && error && (
        <div className="info-box">
          <p className="api-error">{error}</p>
          <p>
            Check that the Analytics API is running on port 8000.
          </p>
        </div>
      )}

      {!sameProperty && !loading && !error && comparisonData && (
        <>
          <div className="info-box">
            <h3>ESG Metrics Comparison</h3>

            <p className="comparison-note">
              {first.entity_id} and {second.entity_id}
              {' '}— Reporting Year: {reportingYear}
            </p>

            <div className="table-wrapper">
              <table className="comparison-table">
                <thead>
                  <tr>
                    <th>ESG Metric</th>
                    <th>{first.entity_name || first.entity_id}</th>
                    <th>{second.entity_name || second.entity_id}</th>
                  </tr>
                </thead>

                <tbody>
                  {METRICS.map((metric) => {
                    const a = getMetric(first, metric.code)
                    const b = getMetric(second, metric.code)

                    return (
                      <tr key={metric.code}>
                        <td>{metric.label}</td>

                        <td>
                          {isUsable(a)
                            ? `${formatNumber(a.standardised_value)} ${a.canonical_unit}`
                            : 'Unavailable'}
                        </td>

                        <td>
                          {isUsable(b)
                            ? `${formatNumber(b.standardised_value)} ${b.canonical_unit}`
                            : 'Unavailable'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            <p className="comparison-note">
              Values are shown in canonical units where available.
              Metrics with missing or incompatible data must not be
              interpreted as valid direct comparisons.
            </p>
          </div>

          <div className="info-box comparison-chart">
            <h3>ESG Metric Visualisation</h3>

            {comparable ? (
              <>
                <p className="subtitle">
                  {METRICS.find(
                    (metric) => metric.code === selectedMetric
                  )?.label}
                  {' '}({firstMetric.canonical_unit})
                </p>

                <div className="chart-container">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" />
                      <YAxis domain={[0, 'auto']} />
                      <Tooltip />
                      <Bar
                        dataKey="value"
                        name="Standardised Value"
                        fill="#40916c"
                        radius={[6, 6, 0, 0]}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </>
            ) : (
              <p className="comparison-note">
                This metric cannot be compared because one or both
                properties have missing or incompatible data.
              </p>
            )}
          </div>

          <div className="info-box comparison-summary">
            <h3>Comparison Summary</h3>

            {comparable ? (
              <>
                <p>
                  <strong>Absolute difference:</strong>{' '}
                  {formatNumber(difference)}
                  {' '}{firstMetric.canonical_unit}
                </p>

                <p>
                  {firstValue === secondValue
                    ? 'Both properties have the same value.'
                    : (
                      firstMetric.performance_direction ===
                      'LOWER_IS_BETTER'
                        ? firstValue < secondValue
                        : firstValue > secondValue
                    )
                      ? `${first.entity_name} has the better value for this metric.`
                      : `${second.entity_name} has the better value for this metric.`}
                </p>
              </>
            ) : (
              <p>
                A numerical comparison is unavailable for
                the selected metric.
              </p>
            )}

            <p className="comparison-note">
              Direct property comparisons are not equivalent to
              peer benchmarking. Each property's benchmark may
              use a different peer cohort.
            </p>
          </div>
        </>
      )}
    </section>
  )
}

export default PropertyComparison
