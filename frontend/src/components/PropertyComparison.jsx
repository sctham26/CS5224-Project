
import { useEffect, useMemo, useState } from 'react'
import EntitySelector from './EntitySelector'
import { getEntityDisplayName, getReportingYears } from './entityUtils'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer
} from 'recharts'

import { API_BASE_URL } from '../api'
import { authenticatedFetch } from '../auth'

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

function PropertyComparison({ entities, entitiesLoading, entitiesError }) {
  const [selectedProperty1, setSelectedProperty1] = useState('')
  const [selectedProperty2, setSelectedProperty2] = useState('')
  const [selectedReportingYear, setSelectedReportingYear] = useState('')
  const [selectedMetric, setSelectedMetric] = useState(
    'ENERGY_INTENSITY_EUI'
  )
  const [comparisonResult, setComparisonResult] = useState(null)

  const property1 = entities.some(
    (entity) => entity.entity_id === selectedProperty1
  ) ? selectedProperty1 : entities[0]?.entity_id ?? ''
  const property2 = entities.some(
    (entity) => entity.entity_id === selectedProperty2
  ) ? selectedProperty2 : entities.find(
    (entity) => entity.entity_id !== property1
  )?.entity_id ?? property1

  const firstEntity = entities.find(
    (entity) => entity.entity_id === property1
  )
  const secondEntity = entities.find(
    (entity) => entity.entity_id === property2
  )
  const firstYears = useMemo(
    () => getReportingYears(firstEntity),
    [firstEntity]
  )
  const secondYears = useMemo(
    () => getReportingYears(secondEntity),
    [secondEntity]
  )
  const sharedYears = useMemo(
    () => firstYears.filter((year) => secondYears.includes(year)),
    [firstYears, secondYears]
  )

  const reportingYear = sharedYears.includes(selectedReportingYear)
    ? selectedReportingYear
    : sharedYears[0] ?? ''
  const comparisonRequestKey = JSON.stringify([
    property1,
    property2,
    reportingYear
  ])
  const hasComparisonSelection =
    !entitiesLoading &&
    !entitiesError &&
    Boolean(firstEntity) &&
    Boolean(secondEntity) &&
    property1 !== property2 &&
    sharedYears.includes(reportingYear)
  const currentComparisonResult =
    comparisonResult?.key === comparisonRequestKey
      ? comparisonResult
      : null
  const comparisonData = currentComparisonResult?.data
  const error = currentComparisonResult?.error
  const loading = Boolean(hasComparisonSelection && !currentComparisonResult)

  useEffect(() => {
    if (
      entitiesLoading ||
      entitiesError ||
      !firstEntity ||
      !secondEntity ||
      property1 === property2 ||
      !sharedYears.includes(reportingYear)
    ) {
      return
    }

    const controller = new AbortController()
    const requestKey = JSON.stringify([property1, property2, reportingYear])

    async function loadComparison() {
      try {
        const fetchProperty = async (entityId) => {
          const response = await authenticatedFetch(
            `${API_BASE_URL}/analysis/${encodeURIComponent(entityId)}` +
              `?scope=asset&reporting_year=${encodeURIComponent(reportingYear)}`,
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
          setComparisonResult({
            key: requestKey,
            data: [first, second],
            error: null
          })
        }
      } catch (err) {
        if (!controller.signal.aborted) {
          setComparisonResult({
            key: requestKey,
            data: null,
            error: err.message
          })
        }
      }
    }

    loadComparison()

    return () => controller.abort()
  }, [
    entitiesError,
    entitiesLoading,
    firstEntity,
    property1,
    property2,
    reportingYear,
    secondEntity,
    sharedYears
  ])

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
          name: getEntityDisplayName(first),
          value: firstValue
        },
        {
          name: getEntityDisplayName(second),
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
          <EntitySelector
            id="compareProperty1"
            label="Property 1"
            entities={entities}
            value={property1}
            onChange={setSelectedProperty1}
            disabled={entitiesLoading || Boolean(entitiesError)}
            loading={entitiesLoading}
          />
        </div>

        <div>
          <EntitySelector
            id="compareProperty2"
            label="Property 2"
            entities={entities}
            value={property2}
            onChange={setSelectedProperty2}
            disabled={entitiesLoading || Boolean(entitiesError)}
            loading={entitiesLoading}
          />
        </div>

        <div>
          <label htmlFor="compareYear">Reporting Year</label>
          <select
            id="compareYear"
            value={reportingYear}
            onChange={(e) => setSelectedReportingYear(e.target.value)}
            disabled={sharedYears.length === 0}
          >
            {sharedYears.length === 0 && (
              <option value="">No shared reporting years</option>
            )}
            {sharedYears.map((year) => (
              <option key={year} value={year}>{year}</option>
            ))}
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

      {entitiesLoading && (
        <div className="info-box" role="status">
          Loading available properties...
        </div>
      )}

      {entitiesError && (
        <div className="info-box">
          <p className="api-error">
            Unable to retrieve properties: {entitiesError}
          </p>
          <p>Check that the Analytics API is running on port 8000.</p>
        </div>
      )}

      {!entitiesLoading && !entitiesError && entities.length === 0 && (
        <div className="info-box">
          The Analytics API did not return any properties.
        </div>
      )}

      {!entitiesLoading &&
        !entitiesError &&
        entities.length === 1 && (
          <div className="info-box">
            At least two properties are required for comparison.
          </div>
        )}

      {sameProperty && entities.length > 1 && (
        <div className="info-box">
          Please select two different properties.
        </div>
      )}

      {!sameProperty &&
        property1 &&
        property2 &&
        sharedYears.length === 0 && (
          <div className="info-box">
            These properties have no shared reporting years.
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
              {getEntityDisplayName(first)} and {getEntityDisplayName(second)}
              {' '}— Reporting Year: {reportingYear}
            </p>

            <div className="table-wrapper">
              <table className="comparison-table">
                <thead>
                  <tr>
                    <th>ESG Metric</th>
                    <th>{getEntityDisplayName(first)}</th>
                    <th>{getEntityDisplayName(second)}</th>
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
                      ? `${getEntityDisplayName(first)} has the better value for this metric.`
                      : `${getEntityDisplayName(second)} has the better value for this metric.`}
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
