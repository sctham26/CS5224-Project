export function getReportingYears(entity) {
  if (!Array.isArray(entity?.reporting_years)) return []

  return [...new Set(
    entity.reporting_years
      .filter((year) => year != null && String(year).trim() !== '')
      .map(String)
  )].sort((first, second) => Number(second) - Number(first))
}

export function getDefaultReportingYear(entity) {
  const years = getReportingYears(entity)
  const latestYear = entity?.latest_reporting_year

  if (latestYear != null && years.includes(String(latestYear))) {
    return String(latestYear)
  }

  return years[0] ?? ''
}

export function getEntityDisplayName(entity) {
  const name = entity?.entity_name?.trim() || 'Unnamed property'
  return `${name} (${entity.entity_id})`
}
