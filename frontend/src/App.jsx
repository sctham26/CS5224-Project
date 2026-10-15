import { useState } from 'react'
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


  // Fictional data for testing our interface
  const metrics = [
    {
      name: 'Energy Intensity',
      value: '145',
      unit: 'kWh/m²/year'
    },
    {
      name: 'Peer Median',
      value: '170',
      unit: 'kWh/m²/year'
    },
    {
      name: 'Percentile',
      value: '72nd',
      unit: 'Illustrative ranking'
    },
    {
      name: 'Performance Gap',
      value: '-14.7%',
      unit: 'Compared with peer median'
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
            <p className="subtitle">
              Building A | Reporting Year: 2025
            </p>

            <div className="metric-grid">
              {metrics.map((metric) => (
                <div className="metric-card" key={metric.name}>
                  <p>{metric.name}</p>
                  <h2>{metric.value}</h2>
                  <span>{metric.unit}</span>
                </div>
              ))}
            </div>

            <div className="info-box">
              <h3>Energy Performance Summary</h3>
              <p>
                Building A has an energy intensity of
                145 kWh/m²/year, compared with a fictional
                peer median of 170 kWh/m²/year.
              </p>
              <p>
                This represents approximately 14.7% lower
                energy intensity than the peer median.
              </p>
            </div>
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
