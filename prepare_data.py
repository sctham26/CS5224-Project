"""Prepare the public ESG CSV. Run: python prepare_data.py

Inputs: two BCA snapshots, curated SGX report values, and grid factors in data/raw.
Output: data/cleaned/public_esg_baseline.csv. No benchmarking or database setup.
"""
from pathlib import Path
import math

import pandas as pd

ROOT = Path(__file__).resolve().parent
RAW = ROOT / 'data/raw'
OUTPUT = ROOT / 'data/cleaned/public_esg_baseline.csv'
COLUMNS = [
    'tenant_id', 'visibility', 'entity_id', 'postal_code', 'entity_name',
    'property_type', 'region', 'reporting_scope', 'reporting_year',
    'period_start', 'period_end', 'gross_floor_area_sqm', 'metric_code',
    'raw_value', 'raw_unit', 'standardised_value', 'canonical_unit',
    'comparability_status', 'operational_boundary', 'source_reference',
]
GREEN_RATINGS = {
    'Uncertified': 0, 'Certified': 1, 'Legislated': 1,
    'Gold': 2, 'GoldPlus': 3, 'Platinum': 4, 'Super Low Energy': 4,
}
EUI_MAX = 2500  # Project screening rule, not a regulatory threshold.


def clean_eui(cell, laboratory_share=0):
    """Return a usable number and status; keep unavailable values out of comparisons."""
    if str(cell).strip().upper() == 'COMBINED':
        return None, 'COMBINED_METERING'
    value = pd.to_numeric(cell, errors='coerce')
    if pd.isna(value) or 0 <= value < 0.000001:
        return None, 'INCOMPLETE_DATA'
    if not math.isfinite(value) or value < 0 or value > EUI_MAX:
        return None, 'ANOMALY_FLAGGED'
    if pd.notna(laboratory_share) and laboratory_share >= 0.5:
        return float(value), 'SPECIAL_USE_ISOLATED'
    return float(value), 'COMPARABLE'


def build_public_data():
    dictionary = pd.read_csv(ROOT / 'docs/metric_dictionary.csv').set_index('metric_code')
    factors = pd.read_csv(RAW / 'grid_emission_factors.csv').set_index('reporting_year')
    records = []

    def add(base, year, metric, raw, unit, value, status, source):
        records.append({**base, 'reporting_year': year,
            'period_start': f'{year}-01-01', 'period_end': f'{year}-12-31',
            'metric_code': metric, 'raw_value': raw, 'raw_unit': unit,
            'standardised_value': value, 'canonical_unit': dictionary.loc[metric, 'canonical_unit'],
            'comparability_status': status, 'source_reference': source})

    # 1. Read both BCA releases. Their column names differ, so list the mapping here.
    old = pd.read_csv(RAW / 'Listing of Building Energy Performance Data 2020.csv')
    latest = pd.read_excel(RAW / 'bca-bebr-data.xlsx', sheet_name='Dataset')
    latest = latest.dropna(subset=['Building Type', 'Building Postal Code'])
    sources = [
        (old, '2020', [2017, 2018, 2019, 2020], 'buildingname', 'mainbuildingfunction', 'grossfloorarea'),
        (latest, 'LATEST', [2022, 2023, 2024, 2025], 'Building Name', 'Building Type', 'Total GFA of Building/ Development (m2)'),
    ]
    for frame, release, years, name_col, type_col, area_col in sources:
        for index, row in frame.iterrows():
            if release == '2020':
                match = pd.Series([str(row['buildingaddress'])]).str.extract(r'(\d{6})').iloc[0, 0]
                postal = str(match) if pd.notna(match) else None
            else:
                postal = str(int(row['Building Postal Code'])).zfill(6)
            base = dict(tenant_id='PUBLIC', visibility='PUBLIC_BASELINE',
                entity_id=f'SG_{postal or "UNKNOWN"}_{release}_{index}', postal_code=postal,
                entity_name=str(row[name_col]).strip() if pd.notna(row[name_col]) else f'UNKNOWN_ASSET_{postal}',
                property_type=str(row[type_col]).strip().upper().replace(' ', '_'),
                region='SG', reporting_scope='ASSET',
                gross_floor_area_sqm=pd.to_numeric(str(row[area_col]).replace(',', ''), errors='coerce'),
                operational_boundary='WHOLE_BUILDING_GFA')
            source = 'BCA_BEBR_2020_CSV' if release == '2020' else 'BCA_BEBR_LATEST_XLSX'

            # 2. Keep missing certification unknown, rather than assuming uncertified.
            if release == '2020':
                rating = str(row['greenmarkrating']).strip() if pd.notna(row['greenmarkrating']) else None
                score = GREEN_RATINGS.get(rating)
                add(base, 2020, 'GREEN_CERT_LEVEL', rating, 'rating', score,
                    'COMPARABLE' if score is not None else 'INCOMPLETE_DATA', source)

            # 3. Clean annual electricity EUI and derive a separately identified CO2 proxy.
            lab_share = pd.to_numeric(row.get('Percentage of GFA for Laboratory Function', 0), errors='coerce')
            for year in years:
                cell = row[str(year) if release == '2020' else f'{year} EUI (kWh/m²/yr)']
                value, status = clean_eui(cell, lab_share)
                raw = None if pd.isna(cell) else cell
                add(base, year, 'ENERGY_INTENSITY_EUI', raw, 'kWh/m2/yr', value, status, source)
                if value is not None:
                    factor = factors.loc[year]
                    add(base, year, 'CARBON_INTENSITY_SCOPE2', value, 'kWh/m2/yr',
                        value * factor.factor_kgco2_per_kwh,
                        'SPECIAL_USE_ISOLATED' if status == 'SPECIAL_USE_ISOLATED' else 'UNIT_CONVERTED',
                        f'{source}_EMA_GEF_{factor.factor_kgco2_per_kwh}_{factor.status}')

    # 4. Convert only the two curated SGX observations; do not infer their boundaries.
    sgx = pd.read_csv(RAW / 'sgx_report_values.csv')
    for row in sgx.itertuples(index=False):
        if row.verification_status != 'VALUE_VERIFIED_BOUNDARY_RESTRICTED':
            raise ValueError(f'Unverified SGX input: {row.source_reference}')
        conversion = {'kWh/m2/yr': 1, 'GJ/m2/yr': 1000 / 3.6}[row.raw_unit]
        base = dict(tenant_id='PUBLIC', visibility='PUBLIC_BASELINE', entity_id=row.entity_id,
            postal_code=None, entity_name=row.entity_name, property_type=row.property_type,
            region=row.region, reporting_scope='PORTFOLIO', gross_floor_area_sqm=None,
            operational_boundary=row.operational_boundary)
        add(base, row.reporting_year, row.metric_code, row.raw_value, row.raw_unit,
            row.raw_value * conversion, 'BOUNDARY_MISMATCH', row.source_reference)
        records[-1].update(period_start=row.period_start, period_end=row.period_end)

    result = pd.DataFrame(records, columns=COLUMNS)
    result['standardised_value'] = result.standardised_value.round(6)
    result['gross_floor_area_sqm'] = pd.to_numeric(result.gross_floor_area_sqm).round(2)
    check_data(result, dictionary)
    return result


def check_data(frame, dictionary):
    """Small data checks, shared by the public output and the private sample."""
    if list(frame.columns) != COLUMNS:
        raise ValueError('Unexpected columns; see docs/data_handoff.md')
    required = [c for c in COLUMNS if c not in {'postal_code', 'gross_floor_area_sqm', 'raw_value', 'standardised_value'}]
    if frame[required].isna().any().any():
        raise ValueError('Missing required identifying/source metadata')
    key = ['tenant_id', 'entity_id', 'reporting_year', 'metric_code', 'reporting_scope']
    if frame.duplicated(key).any():
        raise ValueError('Duplicate entity/year/metric record')
    for row in frame.itertuples(index=False):
        if row.metric_code not in dictionary.index:
            raise ValueError(f'Unknown metric: {row.metric_code}')
        metric = dictionary.loc[row.metric_code]
        if row.canonical_unit != metric.canonical_unit or row.reporting_scope not in metric.reporting_scopes.split(';'):
            raise ValueError(f'Wrong unit or scope: {row.entity_id}/{row.metric_code}')
        value = row.standardised_value
        if pd.notna(value) and not math.isfinite(value):
            raise ValueError('Non-finite cleaned value')
        if row.comparability_status in {'COMPARABLE', 'UNIT_CONVERTED'} and pd.isna(value):
            raise ValueError('Comparable record has no cleaned value')
        if row.comparability_status in {'INCOMPLETE_DATA', 'ANOMALY_FLAGGED', 'COMBINED_METERING'} and pd.notna(value):
            raise ValueError('Unavailable record must have an empty cleaned value')
        start, end = pd.Timestamp(row.period_start), pd.Timestamp(row.period_end)
        if start > end or end.year != row.reporting_year or end != start + pd.DateOffset(years=1) - pd.Timedelta(days=1):
            raise ValueError('Only complete annual periods are supported')
        if (row.visibility == 'PUBLIC_BASELINE') != (row.tenant_id == 'PUBLIC'):
            raise ValueError('Public and private tenant labels disagree')


def main():
    public = build_public_data()
    sample = pd.read_csv(ROOT / 'data/samples/private_esg_sample.csv', dtype={'postal_code': 'string'}, keep_default_na=False, na_values=[''])
    check_data(sample, pd.read_csv(ROOT / 'docs/metric_dictionary.csv').set_index('metric_code'))
    OUTPUT.parent.mkdir(exist_ok=True)
    public.to_csv(OUTPUT, index=False)
    print(f'Saved {len(public):,} public records to {OUTPUT}')
    print(f'Checked {len(sample)} synthetic private records; no analytics or database operations were run.')


if __name__ == '__main__':
    main()
