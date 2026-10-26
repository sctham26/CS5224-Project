import { useMemo, useState } from 'react'
import { getEntityDisplayName } from './entityUtils'

const MAX_VISIBLE_RESULTS = 50

function EntitySelector({
  entities,
  id,
  label,
  value,
  onChange,
  disabled = false,
  loading = false
}) {
  const [search, setSearch] = useState('')
  const [isOpen, setIsOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)

  const selectedEntity = entities.find(
    (entity) => entity.entity_id === value
  )
  const { filteredEntities, totalMatches } = useMemo(() => {
    const query = search.trim().toLocaleLowerCase()
    let totalMatches = 0
    const filteredEntities = []

    for (const entity of entities) {
      const matches = !query || [
        entity.entity_name,
        entity.entity_id,
        entity.postal_code,
        entity.property_type,
        entity.region
      ].some((field) => String(field ?? '').toLocaleLowerCase().includes(query))

      if (matches) {
        totalMatches += 1
        if (filteredEntities.length < MAX_VISIBLE_RESULTS) {
          filteredEntities.push(entity)
        }
      }
    }

    return { filteredEntities, totalMatches }
  }, [entities, search])

  function closeResults() {
    setIsOpen(false)
    setSearch('')
    setActiveIndex(-1)
  }

  function selectEntity(entity) {
    onChange(entity.entity_id)
    closeResults()
  }

  function handleKeyDown(event) {
    if (disabled) return

    if (event.key === 'ArrowDown') {
      event.preventDefault()
      if (!isOpen) {
        setIsOpen(true)
        setSearch('')
        setActiveIndex(0)
      } else {
        setActiveIndex((index) =>
          Math.min(index + 1, filteredEntities.length - 1)
        )
      }
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      if (!isOpen) {
        setIsOpen(true)
        setSearch('')
        setActiveIndex(Math.max(filteredEntities.length - 1, 0))
      } else {
        setActiveIndex((index) => Math.max(index - 1, 0))
      }
    } else if (event.key === 'Enter' && isOpen) {
      event.preventDefault()
      if (activeIndex >= 0 && filteredEntities[activeIndex]) {
        selectEntity(filteredEntities[activeIndex])
      }
    } else if (event.key === 'Escape' && isOpen) {
      event.preventDefault()
      closeResults()
    }
  }

  const listboxId = `${id}-listbox`
  const activeOptionId =
    isOpen && activeIndex >= 0 && filteredEntities[activeIndex]
      ? `${id}-option-${activeIndex}`
      : undefined
  const inputValue = isOpen
    ? search
    : selectedEntity
      ? getEntityDisplayName(selectedEntity)
      : ''

  return (
    <div
      className="entity-selector"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          closeResults()
        }
      }}
    >
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        className="entity-search"
        type="text"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={isOpen && !disabled}
        aria-controls={listboxId}
        aria-activedescendant={activeOptionId}
        aria-describedby={`${id}-status`}
        autoComplete="off"
        value={inputValue}
        onFocus={() => {
          if (!disabled) {
            setIsOpen(true)
            setSearch('')
            setActiveIndex(-1)
          }
        }}
        onChange={(event) => {
          setSearch(event.target.value)
          setActiveIndex(-1)
          setIsOpen(true)
        }}
        onKeyDown={handleKeyDown}
        placeholder={
          loading
            ? 'Loading properties...'
            : entities.length === 0
              ? 'No properties available'
              : 'Search by building name or entity ID'
        }
        disabled={disabled || entities.length === 0}
      />
      {isOpen && !disabled && entities.length > 0 && (
        <div className="entity-results">
          <ul
            id={listboxId}
            className="entity-results-list"
            role="listbox"
            aria-label={`${label} search results`}
          >
            {filteredEntities.map((entity, index) => (
              <li
                id={`${id}-option-${index}`}
                className={[
                  'entity-result',
                  index === activeIndex ? 'active' : '',
                  entity.entity_id === value ? 'selected' : ''
                ].filter(Boolean).join(' ')}
                key={entity.entity_id}
                role="option"
                aria-selected={entity.entity_id === value}
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => selectEntity(entity)}
              >
                <span className="entity-result-name">
                  {entity.entity_name?.trim() || 'Unnamed property'}
                </span>
                <span className="entity-result-id">{entity.entity_id}</span>
              </li>
            ))}
          </ul>
          {filteredEntities.length === 0 && (
            <p className="entity-search-empty" role="status">
              No properties match that search.
            </p>
          )}
          {totalMatches > MAX_VISIBLE_RESULTS && (
            <p className="entity-results-hint">
              Showing the first {MAX_VISIBLE_RESULTS} results. Refine your search.
            </p>
          )}
        </div>
      )}
      <span id={`${id}-status`} className="visually-hidden" aria-live="polite">
        {loading
          ? 'Loading properties.'
          : entities.length === 0
            ? 'No properties available.'
            : isOpen
              ? `${filteredEntities.length} search results available.`
              : selectedEntity
                ? `Selected ${getEntityDisplayName(selectedEntity)}.`
                : 'No property selected.'}
      </span>
    </div>
  )
}

export default EntitySelector
