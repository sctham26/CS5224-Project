import Papa from 'papaparse'

export const SPIP_REQUIRED_FIELDS = [
  'entity_id',
  'reporting_scope',
  'reporting_year',
  'metric_code',
  'standardised_value',
  'canonical_unit',
  'comparability_status',
  'property_type',
  'region',
]

export const ALLOWED_COMPARABILITY_STATUSES = [
  'COMPARABLE',
  'UNIT_CONVERTED',
  'BOUNDARY_MISMATCH',
  'INCOMPLETE_DATA',
  'ANOMALY_FLAGGED',
  'COMBINED_METERING',
  'SPECIAL_USE_ISOLATED',
]

export const MERGED_METRIC_REGISTRY = {
  ENERGY_INTENSITY_EUI: {
    canonical_unit: 'kWh/m2/yr',
    accepted_units: [
      'kWh/m2/yr',
      'kWh/m2/year',
      'MWh/m2/yr',
      'MWh/m2/year',
      'GJ/m2/yr',
      'kWh/sqft/yr',
      'kbtu/m2/year',
    ],
  },
  CARBON_INTENSITY_SCOPE2: {
    canonical_unit: 'kgCO2e/m2/yr',
    accepted_units: ['kgCO2e/m2/yr', 'kgCO2e/m2/year', 'tCO2e/m2/yr', 'tCO2e/m2/year', 'gCO2e/m2/yr'],
  },
  GREEN_CERT_LEVEL: {
    canonical_unit: 'ORDINAL_0_4',
    accepted_units: ['rating', 'ORDINAL_0_4'],
  },
  WATER_INTENSITY: {
    canonical_unit: 'm3/m2/yr',
    accepted_units: ['m3/m2/yr', 'm3/m2/year', 'L/m2/yr', 'liter/m2/year'],
  },
  SCOPE_1_EMISSIONS: {
    canonical_unit: 'tCO2e',
    accepted_units: ['tCO2e', 'kgCO2e', 'ktCO2e'],
  },
  SCOPE_2_EMISSIONS: {
    canonical_unit: 'tCO2e',
    accepted_units: ['tCO2e', 'kgCO2e', 'ktCO2e'],
  },
  CARBON_INTENSITY_SCOPE1_2: {
    canonical_unit: 'kgCO2e/m2/yr',
    accepted_units: ['kgCO2e/m2/yr', 'tCO2e/m2/yr', 'gCO2e/m2/yr'],
  },
  TOTAL_ENERGY_INTENSITY: {
    canonical_unit: 'kWh/m2/yr',
    accepted_units: ['kWh/m2/yr', 'MWh/m2/yr', 'GJ/m2/yr'],
  },
  ENERGY_INTENSITY_REPORTED_TOTAL: {
    canonical_unit: 'kWh/m2/yr',
    accepted_units: ['kWh/m2/yr', 'GJ/m2/yr'],
  },
  WASTE_DIVERSION_RATE: {
    canonical_unit: 'percent',
    accepted_units: ['percent', 'fraction'],
  },
  RENEWABLE_SHARE: {
    canonical_unit: 'percent',
    accepted_units: ['percent', 'fraction'],
  },
}

export function normalizeHeader(value) {
  return String(value ?? '').trim().replace(/\s+/g, '_').toLowerCase()
}

export function parseCsvText(csvText) {
  const result = Papa.parse(csvText, {
    header: true,
    skipEmptyLines: true,
    transformHeader: (header) => String(header ?? '').trim(),
  })

  const rows = Array.isArray(result.data)
    ? result.data.filter((row) => row && Object.values(row).some((value) => String(value ?? '').trim() !== ''))
    : []

  return {
    headers: Array.isArray(result.meta?.fields) ? result.meta.fields.map((field) => String(field).trim()) : [],
    rows,
    parseErrors: Array.isArray(result.errors) ? result.errors : [],
  }
}

function coerceString(value) {
  return String(value ?? '').trim()
}

function compareNormalized(a, b) {
  return coerceString(a).toLowerCase() === coerceString(b).toLowerCase()
}

export function buildDefaultColumnMap(headers, { entityId = '', reportingYear = '', selectedEntity = null, scope = 'ASSET' } = {}) {
  const lookup = new Set(headers.map((header) => normalizeHeader(header)))
  const mapping = {}

  for (const field of SPIP_REQUIRED_FIELDS) {
    const normalizedField = normalizeHeader(field)
    const directMatch = headers.find((header) => normalizeHeader(header) === normalizedField)

    if (directMatch) {
      mapping[field] = { type: 'source', header: directMatch }
      continue
    }

    if (field === 'entity_id') {
      mapping[field] = { type: 'fixed', value: String(entityId ?? '') }
      continue
    }

    if (field === 'reporting_year') {
      mapping[field] = { type: 'fixed', value: String(reportingYear ?? '') }
      continue
    }

    if (field === 'reporting_scope') {
      mapping[field] = { type: 'fixed', value: String(scope).toUpperCase() }
      continue
    }

    if (field === 'property_type' && selectedEntity?.property_type) {
      mapping[field] = { type: 'fixed', value: String(selectedEntity.property_type) }
      continue
    }

    if (field === 'region' && selectedEntity?.region) {
      mapping[field] = { type: 'fixed', value: String(selectedEntity.region) }
      continue
    }

    const fallbacks = {
      metric_code: ['metric', 'metric_code'],
      standardised_value: ['standardised_value', 'value'],
      canonical_unit: ['canonical_unit', 'unit'],
      comparability_status: ['comparability_status', 'status'],
      property_type: ['property_type', 'asset_type'],
      region: ['region', 'geo_region'],
      entity_id: ['entity_id', 'property_id'],
      reporting_scope: ['reporting_scope', 'scope'],
      reporting_year: ['reporting_year', 'year'],
    }

    for (const candidate of fallbacks[field] ?? []) {
      if (lookup.has(normalizeHeader(candidate))) {
        mapping[field] = { type: 'source', header: headers.find((header) => normalizeHeader(header) === normalizeHeader(candidate)) }
        break
      }
    }

    if (!mapping[field]) {
      mapping[field] = { type: 'source', header: '' }
    }
  }

  return mapping
}

export function generateStandardisedCsv(rows, mapping, context = {}) {
  if (!Array.isArray(rows) || rows.length === 0) {
    throw new Error('The selected CSV does not contain any data rows.')
  }

  const selectedEntityId = coerceString(context.entityId)
  const selectedYear = coerceString(context.reportingYear)
  const selectedEntity = context.selectedEntity ?? null
  const errors = []
  const prepared = []

  for (const [index, row] of rows.entries()) {
    const resolved = {}

    for (const field of SPIP_REQUIRED_FIELDS) {
      const config = mapping[field] || { type: 'source', header: '' }
      const rawValue = config.type === 'source'
        ? row[config.header]
        : config.type === 'fixed'
          ? config.value
          : ''

      resolved[field] = coerceString(rawValue)
    }

    if (!resolved.entity_id) {
      errors.push(`Row ${index + 2}: entity_id is required.`)
      continue
    }

    if (!selectedEntityId || !compareNormalized(resolved.entity_id, selectedEntityId)) {
      errors.push(`Row ${index + 2}: entity_id must match the selected property (${selectedEntityId || 'unknown'}).`)
    }

    if (!resolved.reporting_scope) {
      errors.push(`Row ${index + 2}: reporting_scope is required.`)
    } else if (!['ASSET', 'PORTFOLIO'].includes(resolved.reporting_scope.toUpperCase())) {
      errors.push(`Row ${index + 2}: reporting_scope must be ASSET or PORTFOLIO.`)
    }

    if (!resolved.reporting_year) {
      errors.push(`Row ${index + 2}: reporting_year is required.`)
    } else if (!compareNormalized(resolved.reporting_year, selectedYear)) {
      errors.push(`Row ${index + 2}: reporting_year must match the selected year (${selectedYear}).`)
    }

    if (!resolved.metric_code) {
      errors.push(`Row ${index + 2}: metric_code is required.`)
      continue
    }

    const metricSpec = MERGED_METRIC_REGISTRY[resolved.metric_code]
    if (!metricSpec) {
      errors.push(`Row ${index + 2}: metric_code "${resolved.metric_code}" is not accepted by the SPIP registry.`)
      continue
    }

    if (!resolved.standardised_value) {
      errors.push(`Row ${index + 2}: standardised_value is required for metric ${resolved.metric_code}.`)
      continue
    }

    const parsedNumeric = Number(resolved.standardised_value)
    if (!Number.isFinite(parsedNumeric)) {
      errors.push(`Row ${index + 2}: standardised_value must be a finite numeric value for metric ${resolved.metric_code}.`)
      continue
    }

    if (!resolved.canonical_unit) {
      errors.push(`Row ${index + 2}: canonical_unit is required for metric ${resolved.metric_code}.`)
      continue
    }

    const canonicalUnit = resolved.canonical_unit.trim()
    if (!metricSpec.accepted_units.includes(canonicalUnit)) {
      errors.push(`Row ${index + 2}: canonical_unit "${canonicalUnit}" is invalid for metric ${resolved.metric_code}. Accepted units: ${metricSpec.accepted_units.join(', ')}.`)
      continue
    }

    if (!resolved.comparability_status) {
      errors.push(`Row ${index + 2}: comparability_status is required.`)
      continue
    }

    const statusValue = resolved.comparability_status.trim().toUpperCase()
    if (!ALLOWED_COMPARABILITY_STATUSES.includes(statusValue)) {
      errors.push(`Row ${index + 2}: comparability_status "${statusValue}" is not accepted.`)
      continue
    }

    if (!resolved.property_type) {
      errors.push(`Row ${index + 2}: property_type is required.`)
      continue
    }

    if (selectedEntity?.property_type && !compareNormalized(resolved.property_type, selectedEntity.property_type)) {
      errors.push(`Row ${index + 2}: property_type must match the selected property (${selectedEntity.property_type}).`)
    }

    if (!resolved.region) {
      errors.push(`Row ${index + 2}: region is required.`)
      continue
    }

    if (selectedEntity?.region && !compareNormalized(resolved.region, selectedEntity.region)) {
      errors.push(`Row ${index + 2}: region must match the selected property region (${selectedEntity.region}).`)
    }

    prepared.push({
      entity_id: resolved.entity_id,
      reporting_scope: resolved.reporting_scope.toUpperCase(),
      reporting_year: String(resolved.reporting_year),
      metric_code: resolved.metric_code,
      standardised_value: String(parsedNumeric),
      canonical_unit: canonicalUnit,
      comparability_status: statusValue,
      property_type: resolved.property_type,
      region: resolved.region,
    })
  }

  if (errors.length > 0) {
    throw new Error(errors.join(' '))
  }

  const csvText = Papa.unparse(prepared, {
    columns: SPIP_REQUIRED_FIELDS,
    quotes: true,
    newline: '\n',
  })

  return {
    csvText,
    rows: prepared,
    previewRows: prepared.slice(0, 5),
  }
}

export function makeMappedFile(csvText, originalFileName) {
  const basename = String(originalFileName || 'mapped-upload.csv').replace(/\.csv$/i, '')
  return new File([csvText], `${basename}-mapped.csv`, { type: 'text/csv' })
}
