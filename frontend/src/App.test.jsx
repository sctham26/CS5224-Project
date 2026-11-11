import { render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'

import App from './App'
import { authenticatedFetch } from './auth'

vi.mock('./api', () => ({
  API_BASE_URL: '/api',
}))

vi.mock('./auth', () => ({
  authenticatedFetch: vi.fn(),
}))

beforeEach(() => {
  vi.clearAllMocks()
})

it('displays an insufficient peer sample message when benchmarking is unavailable', async () => {
  authenticatedFetch.mockImplementation(async (url) => {
    if (url.includes('/entities')) {
      return {
        ok: true,
        json: async () => ({
          entities: [{
            entity_id: 'A001',
            entity_name: 'Alpha Tower',
            reporting_years: [2025],
            latest_reporting_year: 2025,
          }],
        }),
      }
    }

    if (url.includes('/analysis')) {
      return {
        ok: true,
        json: async () => ({
          entity_id: 'A001',
          entity_name: 'Alpha Tower',
          reporting_year: 2025,
          peer_cohort: {
            property_type: 'OFFICE',
            region: 'SG',
            sample_size_n: 3,
            fallback_applied: false,
          },
          metrics: [{
            metric_code: 'ENERGY_INTENSITY_EUI',
            standardised_value: 120,
            canonical_unit: 'kWh/m2/yr',
            comparability_status: 'COMPARABLE',
            benchmark: null,
            gap_analysis: {
              gap_type: null,
              is_flagged: null,
              threshold_percentile: 40,
              recommendation_signal: 'Benchmark unavailable due to insufficient peers.',
            },
          }],
        }),
      }
    }

    throw new Error(`Unexpected URL: ${url}`)
  })

  render(<App />)

  expect(await screen.findByText('Property ESG Dashboard')).toBeInTheDocument()
  expect(await screen.findByText('Insufficient peer sample')).toBeInTheDocument()
  expect(screen.queryByText('Not Flagged')).not.toBeInTheDocument()
  expect(screen.queryByText(/No ESG gaps flagged/)).not.toBeInTheDocument()
})

it('shows a normal flagged benchmark result when peers are sufficient', async () => {
  authenticatedFetch.mockImplementation(async (url) => {
    if (url.includes('/entities')) {
      return {
        ok: true,
        json: async () => ({
          entities: [{
            entity_id: 'A001',
            entity_name: 'Alpha Tower',
            reporting_years: [2025],
            latest_reporting_year: 2025,
          }],
        }),
      }
    }

    if (url.includes('/analysis')) {
      return {
        ok: true,
        json: async () => ({
          entity_id: 'A001',
          entity_name: 'Alpha Tower',
          reporting_year: 2025,
          peer_cohort: {
            property_type: 'OFFICE',
            region: 'SG',
            sample_size_n: 6,
            fallback_applied: false,
          },
          metrics: [{
            metric_code: 'ENERGY_INTENSITY_EUI',
            standardised_value: 182.5,
            canonical_unit: 'kWh/m2/yr',
            comparability_status: 'UNIT_CONVERTED',
            benchmark: {
              peer_median: 160,
              relative_rank: 3,
              empirical_percentile: 20,
            },
            gap_analysis: {
              gap_type: 'PERFORMANCE_GAP',
              is_flagged: true,
              threshold_percentile: 40,
              delta_to_peer_median: 22.5,
              recommendation_signal: 'Benchmark is under threshold.',
            },
          }],
        }),
      }
    }

    throw new Error(`Unexpected URL: ${url}`)
  })

  render(<App />)

  expect(await screen.findByText('Property ESG Dashboard')).toBeInTheDocument()
  expect(await screen.findByText('Flagged')).toBeInTheDocument()
  expect(screen.queryByText('Insufficient peer sample')).not.toBeInTheDocument()
})
