import { describe, expect, it } from 'vitest'

import {
  buildDefaultColumnMap,
  generateStandardisedCsv,
  parseCsvText,
} from './csvColumnMapper'

describe('csvColumnMapper', () => {
  it('parses quoted CSV fields and produces the standardised SPIP layout', () => {
    const csvText = [
      'Asset ID,Year,Metric,Value,Unit,Status,Property Type,Region',
      '"A001","2025","ENERGY_INTENSITY_EUI","182.5","kWh/m2/yr","COMPARABLE","OFFICE","SG"',
      '"A001","2025","CARBON_INTENSITY_SCOPE2","73.365","kgCO2e/m2/yr","UNIT_CONVERTED","OFFICE","SG"',
    ].join('\n')

    const { headers, rows } = parseCsvText(csvText)
    const mapping = buildDefaultColumnMap(headers, {
      entityId: 'A001',
      reportingYear: '2025',
      selectedEntity: { property_type: 'OFFICE', region: 'SG' },
      scope: 'ASSET',
    })

    const converted = generateStandardisedCsv(rows, mapping, {
      entityId: 'A001',
      reportingYear: '2025',
      scope: 'ASSET',
      selectedEntity: { property_type: 'OFFICE', region: 'SG' },
    })

    expect(converted.rows).toHaveLength(2)
    expect(converted.csvText).toContain('entity_id')
    expect(converted.csvText).toContain('reporting_scope')
    expect(converted.csvText).toContain('metric_code')
    expect(converted.rows[0].metric_code).toBe('ENERGY_INTENSITY_EUI')
    expect(converted.rows[0].canonical_unit).toBe('kWh/m2/yr')
    expect(converted.rows[0].comparability_status).toBe('COMPARABLE')
  })

  it('rejects CSVs with missing required columns', () => {
    const csvText = 'Asset ID,Year,Metric,Value\nA001,2025,ENERGY_INTENSITY_EUI,182.5\n'
    const { rows } = parseCsvText(csvText)
    const mapping = buildDefaultColumnMap(['Asset ID', 'Year', 'Metric', 'Value'], {
      entityId: 'A001',
      reportingYear: '2025',
      selectedEntity: { property_type: 'OFFICE', region: 'SG' },
    })

    expect(() => generateStandardisedCsv(rows, mapping, {
      entityId: 'A001',
      reportingYear: '2025',
      selectedEntity: { property_type: 'OFFICE', region: 'SG' },
    })).toThrow(/canonical_unit|reporting_scope|property_type|region/i)
  })

  it('rejects invalid metric or unit combinations', () => {
    const csvText = 'Asset ID,Year,Metric,Value,Unit,Status,Property Type,Region,Reporting Scope\nA001,2025,BOGUS_METRIC,182.5,kWh/m2/yr,COMPARABLE,OFFICE,SG,ASSET\n'
    const { rows } = parseCsvText(csvText)
    const mapping = {
      entity_id: { type: 'source', header: 'Asset ID' },
      reporting_scope: { type: 'source', header: 'Reporting Scope' },
      reporting_year: { type: 'fixed', value: '2025' },
      metric_code: { type: 'source', header: 'Metric' },
      standardised_value: { type: 'source', header: 'Value' },
      canonical_unit: { type: 'source', header: 'Unit' },
      comparability_status: { type: 'source', header: 'Status' },
      property_type: { type: 'source', header: 'Property Type' },
      region: { type: 'source', header: 'Region' },
    }

    expect(() => generateStandardisedCsv(rows, mapping, { entityId: 'A001', reportingYear: '2025', selectedEntity: { property_type: 'OFFICE', region: 'SG' } })).toThrow(/BOGUS_METRIC|not accepted/i)
  })

  it('rejects mismatched entity or reporting year', () => {
    const csvText = 'Asset ID,Year,Metric,Value,Unit,Status,Property Type,Region,Reporting Scope\nA999,2025,ENERGY_INTENSITY_EUI,182.5,kWh/m2/yr,COMPARABLE,OFFICE,SG,ASSET\n'
    const { rows } = parseCsvText(csvText)
    const mapping = {
      entity_id: { type: 'source', header: 'Asset ID' },
      reporting_scope: { type: 'source', header: 'Reporting Scope' },
      reporting_year: { type: 'source', header: 'Year' },
      metric_code: { type: 'source', header: 'Metric' },
      standardised_value: { type: 'source', header: 'Value' },
      canonical_unit: { type: 'source', header: 'Unit' },
      comparability_status: { type: 'source', header: 'Status' },
      property_type: { type: 'source', header: 'Property Type' },
      region: { type: 'source', header: 'Region' },
    }

    expect(() => generateStandardisedCsv(rows, mapping, {
      entityId: 'A001',
      reportingYear: '2025',
      selectedEntity: { property_type: 'OFFICE', region: 'SG' },
    })).toThrow(/entity_id must match/i)
  })

  it('accepts a successful mapping with fixed values and selected metadata', () => {
    const csvText = 'Metric,Value,Unit,Status,Property Type,Region\nENERGY_INTENSITY_EUI,100.5,kWh/m2/yr,COMPARABLE,OFFICE,SG\n'
    const { headers, rows } = parseCsvText(csvText)
    const mapping = buildDefaultColumnMap(headers, {
      entityId: 'A001',
      reportingYear: '2025',
      selectedEntity: { property_type: 'OFFICE', region: 'SG' },
      scope: 'ASSET',
    })

    mapping.metric_code = { type: 'source', header: 'Metric' }
    mapping.standardised_value = { type: 'source', header: 'Value' }
    mapping.canonical_unit = { type: 'source', header: 'Unit' }
    mapping.comparability_status = { type: 'source', header: 'Status' }
    mapping.property_type = { type: 'source', header: 'Property Type' }
    mapping.region = { type: 'source', header: 'Region' }

    const result = generateStandardisedCsv(rows, mapping, {
      entityId: 'A001',
      reportingYear: '2025',
      scope: 'ASSET',
      selectedEntity: { property_type: 'OFFICE', region: 'SG' },
    })

    expect(result.rows[0].entity_id).toBe('A001')
    expect(result.rows[0].reporting_year).toBe('2025')
    expect(result.rows[0].reporting_scope).toBe('ASSET')
  })
})
