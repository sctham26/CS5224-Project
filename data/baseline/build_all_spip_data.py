import pandas as pd
import numpy as np

# 1. Load your two raw BCA files
df_2020 = pd.read_csv('Listing of Building Energy Performance Data 2020.csv')
df_latest = pd.read_excel('bca-bebr-data.xlsx', sheet_name='Dataset')

df_2020['postal_code'] = df_2020['buildingaddress'].astype(str).str.extract(r'(\d{6})')[0]
df_latest['postal_code'] = (
    pd.to_numeric(df_latest['Building Postal Code'], errors='coerce')
    .dropna().astype(int).astype(str).str.zfill(6)
)

def map_sg_region(postal):
    if pd.isna(postal) or len(str(postal)) < 2:
        return 'SG_OTHER'
    sector = str(postal)[:2]
    if sector in {'01', '02', '03', '04', '05', '06', '07', '08'}:
        return 'SG_CBD'
    if sector in {'09', '10', '22', '23'}:
        return 'SG_CENTRAL_ORCHARD'
    if sector in {'11', '12', '13', '60', '61', '62', '63', '64', '65', '66', '67', '68'}:
        return 'SG_WEST'
    if sector in {'38', '39', '40', '41', '42', '43', '44', '45', '46', '47', '48', '49', '50', '51', '52'}:
        return 'SG_EAST'
    return 'SG_NORTH_NE'

gm_map = {'Platinum': 4, 'GoldPlus': 3, 'Gold': 2, 'Certified': 1, 'Legislated': 1}
df_2020['gm_score'] = df_2020['greenmarkrating'].map(gm_map).fillna(0)

EMA_GRID_EF = {
    2017: 0.4192, 2018: 0.4188, 2019: 0.4085, 2020: 0.4085,
    2022: 0.4168, 2023: 0.4120, 2024: 0.4120, 2025: 0.4120
}

records = []

# Process 2020 CSV (Years 2017-2020 + Green Mark)
for idx, row in df_2020.iterrows():
    postal = row['postal_code']
    entity_id = f"SG_{postal}_{idx}" if pd.notna(postal) else f"SG_2020_{idx}"
    bname = str(row['buildingname']).strip()
    btype = str(row['mainbuildingfunction']).strip().upper().replace(' ', '_')
    region = map_sg_region(postal)
    gfa = pd.to_numeric(str(row['grossfloorarea']).replace(',', ''), errors='coerce')

    records.append({
        'tenant_id': 'PUBLIC', 'visibility': 'PUBLIC_BASELINE',
        'entity_id': entity_id, 'postal_code': postal, 'entity_name': bname,
        'property_type': btype, 'region': region, 'reporting_scope': 'ASSET',
        'reporting_year': 2020, 'gross_floor_area_sqm': gfa,
        'metric_code': 'GREEN_CERT_LEVEL', 'raw_value': row['gm_score'],
        'raw_unit': str(row['greenmarkrating']) if pd.notna(row['greenmarkrating']) else 'Uncertified',
        'standardised_value': row['gm_score'], 'canonical_unit': 'ORDINAL_0_4',
        'comparability_status': 'COMPARABLE', 'source_reference': 'BCA_BEBR_2020_CSV'
    })

    for yr_str in ['2017', '2018', '2019', '2020']:
        yr = int(yr_str)
        eui_val = pd.to_numeric(row[yr_str], errors='coerce')
        status = 'COMPARABLE' if (pd.notna(eui_val) and 0 < eui_val <= 2000) else ('INCOMPLETE_DATA' if pd.isna(eui_val) else 'ANOMALY_FLAGGED')
        std_val = eui_val if status == 'COMPARABLE' else np.nan
        records.append({
            'tenant_id': 'PUBLIC', 'visibility': 'PUBLIC_BASELINE',
            'entity_id': entity_id, 'postal_code': postal, 'entity_name': bname,
            'property_type': btype, 'region': region, 'reporting_scope': 'ASSET',
            'reporting_year': yr, 'gross_floor_area_sqm': gfa,
            'metric_code': 'ENERGY_INTENSITY_EUI', 'raw_value': eui_val, 'raw_unit': 'kWh/m2/yr',
            'standardised_value': std_val, 'canonical_unit': 'kWh/m2/yr',
            'comparability_status': status, 'source_reference': 'BCA_BEBR_2020_CSV'
        })
        if status == 'COMPARABLE':
            records.append({
                'tenant_id': 'PUBLIC', 'visibility': 'PUBLIC_BASELINE',
                'entity_id': entity_id, 'postal_code': postal, 'entity_name': bname,
                'property_type': btype, 'region': region, 'reporting_scope': 'ASSET',
                'reporting_year': yr, 'gross_floor_area_sqm': gfa,
                'metric_code': 'CARBON_INTENSITY', 'raw_value': eui_val, 'raw_unit': 'kWh/m2/yr_derived',
                'standardised_value': round(eui_val * EMA_GRID_EF[yr], 4), 'canonical_unit': 'kgCO2e/m2/yr',
                'comparability_status': 'UNIT_CONVERTED', 'source_reference': 'BCA_BEBR_2020_CSV_EMA_EF'
            })

# Process Latest BCA XLSX (Years 2022-2025)
for idx, row in df_latest.iterrows():
    if pd.isna(row['Building Name']) and pd.isna(row['Building Type']):
        continue
    postal = row['postal_code']
    entity_id = f"SG_{postal}_{idx}" if pd.notna(postal) else f"SG_LATEST_{idx}"
    bname = str(row['Building Name']).strip()
    btype = str(row['Building Type']).strip().upper().replace(' ', '_')
    region = map_sg_region(postal)
    gfa = pd.to_numeric(row['Total GFA of Building/ Development (m2)'], errors='coerce')

    for yr in [2022, 2023, 2024, 2025]:
        col = f'{yr} EUI (kWh/m²/yr)'
        eui_val = pd.to_numeric(row[col], errors='coerce')
        status = 'COMPARABLE' if (pd.notna(eui_val) and 0 < eui_val <= 2500) else ('INCOMPLETE_DATA' if pd.isna(eui_val) else 'ANOMALY_FLAGGED')
        std_val = eui_val if status == 'COMPARABLE' else np.nan
        records.append({
            'tenant_id': 'PUBLIC', 'visibility': 'PUBLIC_BASELINE',
            'entity_id': entity_id, 'postal_code': postal, 'entity_name': bname,
            'property_type': btype, 'region': region, 'reporting_scope': 'ASSET',
            'reporting_year': yr, 'gross_floor_area_sqm': gfa,
            'metric_code': 'ENERGY_INTENSITY_EUI', 'raw_value': eui_val, 'raw_unit': 'kWh/m2/yr',
            'standardised_value': std_val, 'canonical_unit': 'kWh/m2/yr',
            'comparability_status': status, 'source_reference': 'BCA_BEBR_LATEST_XLSX'
        })
        if status == 'COMPARABLE':
            records.append({
                'tenant_id': 'PUBLIC', 'visibility': 'PUBLIC_BASELINE',
                'entity_id': entity_id, 'postal_code': postal, 'entity_name': bname,
                'property_type': btype, 'region': region, 'reporting_scope': 'ASSET',
                'reporting_year': yr, 'gross_floor_area_sqm': gfa,
                'metric_code': 'CARBON_INTENSITY', 'raw_value': eui_val, 'raw_unit': 'kWh/m2/yr_derived',
                'standardised_value': round(eui_val * EMA_GRID_EF[yr], 4), 'canonical_unit': 'kgCO2e/m2/yr',
                'comparability_status': 'UNIT_CONVERTED', 'source_reference': 'BCA_BEBR_LATEST_XLSX_EMA_EF'
            })

df_out = pd.DataFrame(records)
df_out.to_csv('spip_harmonised_public_baseline.csv', index=False)
print(f"Done! Saved spip_harmonised_public_baseline.csv with {len(df_out)} rows.")