# ESG Data Collection, Preparation and Handoff Report

## 1. Introduction

The work done so far covers five responsibilities:

1. Collect and clean public real-estate environmental, social and governance (ESG) data from BCA and SGX-listed company reports.
2. Define the metrics, units, reporting periods and sources used by the prototype.
3. Prepare public and synthetic private datasets for integration and testing.
4. Document data availability, limitations, user requirements and competitor analysis.
5. Prepare a common dataset format for coordination with the analytics module.

The current datasets mainly cover environmental performance. They do not provide a complete assessment of social and governance performance.

## 2. Data Collection and Source Coverage

### 2.1 BCA building data

Two local Building and Construction Authority (BCA) files were used.

| Source file | Data available |
| --- | --- |
| `data/raw/Listing of Building Energy Performance Data 2020.csv` | 564 source assets, annual electricity energy use intensity for 2017–2020, building information and Green Mark ratings |
| `data/raw/bca-bebr-data.xlsx` | Electricity energy use intensity for 2022–2025, building information and floor areas. Gas intensity and building-function information are also present, although gas intensity is not extracted into the cleaned dataset |

The newer workbook's `Dataset` sheet contains 997 rows. Of these, 995 are asset rows, one is blank and one is an explanatory footnote. The non-asset rows were removed. Among the asset rows, 49 contain combined-metering placeholders rather than independent annual numeric readings.

The original BCA files have been preserved. Their original download dates and exact historical download links were not recorded. The [BCA Building Energy Benchmarking Report page](https://www1.bca.gov.sg/sustainability/legislation-on-environmental-sustainability-for-buildings/existing-buildings/building-energy-benchmarking-report/) provides the source context.

### 2.2 Reports from SGX-listed organisations

Two public report values were retained. Their sources and extraction details are recorded in `data/raw/sgx_report_values.csv`.

| Organisation and reporting year | Reported value | Standardised value | Important limitation |
| --- | --- | --- | --- |
| Keppel REIT, 2024 | 1.33 GJ/m² | 369.444444 kWh/m²/year | Includes fuel, electricity and cooling, measured against landlord-controlled floor area |
| CapitaLand Investment, 2024 | 89.6 kWh/m² | 89.6 kWh/m²/year | Covers a global portfolio and a source-defined floor-area boundary that needs further review before peer comparison |

The Keppel value appears on PDF page 18, printed page 87, of its [2024 Sustainability Report](https://www.keppelreit.com/file/sustainability/sustainability-report/kreit-sr24-website.pdf). The CapitaLand Investment value appears in assurance Table A on PDF page 53, printed page 50, of its [2024 Global Sustainability Report](https://www.capitaland.com/content/dam/capitalandinvestment/sustainability/global-sustainability-reports/CLI-GSR-2024.pdf).

These values are useful examples of public portfolio disclosures. However, they cannot be directly compared with BCA whole-building electricity data. They cover different energy sources, floor areas and geographical markets. They are therefore retained with the status `BOUNDARY_MISMATCH` for the default BCA comparison. Additional verified and compatible report values are needed before meaningful portfolio benchmarking can be performed.

### 2.3 Electricity emission factors

An electricity emission factor estimates the carbon dioxide released per unit of electricity generated. The factors used by this project are stored in `data/raw/grid_emission_factors.csv`, together with their source links and publication status.

Historical factors are supported by the saved [EMA dataset from data.gov.sg](https://data.gov.sg/datasets/d_3de362b580b2dd2fd50cc1006d4edd4f/view). Its API response is retained in `data/raw/ema_historical_grid_factors.json`. The 2022 factor is supported by [NEA's FY2023 report, footnote 31](https://www.nea.gov.sg/docs/default-source/asr/fy2023/nea-asr-fy23.pdf), which cites EMA. The 2023 and 2024 factors are supported by [EMA's Singapore Energy Statistics, Chapter 2](https://www.ema.gov.sg/resources/singapore-energy-statistics/chapter2).

For 2025, the project uses the 2024 value of **0.402 kgCO2/kWh as a provisional assumption**. It is not presented as a published 2025 factor. The factors are versioned inputs; later official revisions require a source review and a new dataset build.

## 3. Metrics, Units and Reporting Periods

### 3.1 Metric definitions

A metric dictionary was prepared in `docs/metric_dictionary.csv`. It is a data file read by the preparation script. It records each metric's code, standard unit, performance direction, reporting scope and availability.

| Metric code | Meaning | Standard unit | Current availability |
| --- | --- | --- | --- |
| `ENERGY_INTENSITY_EUI` | Annual electricity use divided by floor area | kWh/m²/year | Public BCA data and private sample |
| `CARBON_INTENSITY_SCOPE2` | Estimated electricity-related carbon dioxide divided by floor area | kgCO2e/m²/year, with the proxy limitation explained below | Derived BCA data and private sample |
| `ENERGY_INTENSITY_REPORTED_TOTAL` | Total energy intensity as defined by the source report | kWh/m²/year | Two restricted SGX disclosures |
| `GREEN_CERT_LEVEL` | A numerical representation of a Green Mark rating | Ordinal score from 0 to 4 | Older BCA certification data and private sample |
| `WATER_INTENSITY` | Annual water use divided by floor area | m³/m²/year | Private sample only |
| `SCOPE_1_EMISSIONS` | Direct emissions from the example fuel use | tCO2e | Synthetic utility examples only |
| `SCOPE_2_EMISSIONS` | Electricity-related emissions in the example calculations | tCO2e | Synthetic utility examples only |
| `CARBON_INTENSITY_SCOPE1_2` | Combined Scope 1 and Scope 2 emissions divided by floor area | kgCO2e/m²/year | Synthetic utility examples only |
| `TOTAL_ENERGY_INTENSITY` | Electricity, gas and diesel energy divided by floor area | kWh/m²/year | Synthetic utility examples only |

Lower values represent better performance for the energy, water and emissions metrics. Higher scores represent higher certification levels. Supporting a metric in the dictionary does not mean that a public comparison dataset exists for it.

The derived carbon metric is calculated as:

```text
Electricity carbon intensity = electricity EUI × reporting-year grid emission factor
```

This is a **CO2-only estimate from grid electricity**. It excludes direct fuel emissions and other greenhouse gases. The existing `kgCO2e` unit label is retained in the dataset, but the value must be described as a CO2 proxy when displayed. It must not be treated as a complete Scope 2 greenhouse-gas inventory or combined with differently defined carbon disclosures.

### 3.2 Unit conversions

The following conversions are used in preparation or illustrated in the test data.

| Conversion | Calculation |
| --- | --- |
| MWh to kWh | Multiply by 1,000 |
| GJ to kWh | Multiply by 1,000 / 3.6 |
| kWh/sqft/year to kWh/m²/year | Multiply by 10.7639104 |
| Floor area in sqft to m² | Divide by 10.7639104 |
| tCO2e/m²/year to kgCO2e/m²/year | Multiply by 1,000 |
| gCO2e/m²/year to kgCO2e/m²/year | Divide by 1,000 |
| L/m²/year to m³/m²/year | Divide by 1,000 |
| ML/m²/year to m³/m²/year | Multiply by 1,000 |
| kgCO2e to tCO2e | Divide by 1,000 |
| ktCO2e to tCO2e | Multiply by 1,000 |

Green Mark text is mapped as follows: explicit Uncertified = 0; Certified or Legislated = 1; Gold = 2; GoldPlus = 3; Platinum or Super Low Energy = 4. Missing or unknown ratings remain unavailable. This is a project ordering, not a measure of equal differences in energy savings. The treatment of `Legislated` requires domain review before any regulatory interpretation.

### 3.3 Reporting periods and scope

Each record includes its actual start and end dates. `reporting_year` is the year containing the period end. Current records cover complete January–December years. There is no BCA data for 2021 in the supplied files.

Future financial-year disclosures must retain their actual dates. Partial-year observations must not be silently converted into annual values. Comparisons should use matching periods.

An `ASSET` record represents an individual building. A `PORTFOLIO` record represents a group of properties. These scopes must remain separate during comparison. The measurement boundary also matters: whole-building data, common-area data and landlord-controlled data can have different meanings even when their units match.

## 4. Data Preparation Method

The public dataset is produced by one script, `prepare_data.py`. Its process has four main stages.

First, the script reads the BCA files and maps their different column names into one format. It extracts postal codes, standardises building-type labels, removes non-asset rows and assigns source-specific identifiers. Missing building names receive an `UNKNOWN_ASSET_<postal>` label. Singapore assets use the region label `SG`; the script does not infer detailed districts from postal codes.

Second, it cleans the annual electricity readings and older certification ratings. Original observations are retained in the raw-value fields, while unavailable or unsuitable readings receive an explanatory status.

Third, it derives the electricity carbon estimates using the reporting-year factors. It also converts the curated SGX energy values while preserving their different measurement boundaries.

Finally, it checks the public dataset and the prepared private sample. The checks cover column structure, required metadata, duplicate records, metric codes, standard units, supported scopes, annual dates and the consistency of missing values with their status. These are data checks; they do not validate a deployed analytics or security system.

### 4.1 Cleaning rules

| Status | Meaning and treatment |
| --- | --- |
| `COMPARABLE` | A value is retained in the standard unit. Further peer filters are still required |
| `UNIT_CONVERTED` | A compatible conversion or documented carbon estimate was applied |
| `INCOMPLETE_DATA` | A value is missing, or EUI is zero or below 0.000001. The cleaned value is left empty |
| `ANOMALY_FLAGGED` | EUI is negative or above 2,500, or the private example has an unsupported unit. The cleaned value is left empty |
| `COMBINED_METERING` | A BCA `Combined` placeholder is retained without an independent numeric value |
| `SPECIAL_USE_ISOLATED` | A valid observation has laboratory floor-area share of at least 50%; its value is retained but excluded from ordinary commercial peers |
| `BOUNDARY_MISMATCH` | A value is retained but its measurement boundary is unsuitable for the default whole-building comparison |

The EUI limit and laboratory-share cutoff are project screening choices, not regulatory thresholds. The cause of a zero or negative reading is not assumed. In particular, a missing Green Mark rating is not interpreted as proof that a building is uncertified. This preserves 247 older certification observations as unavailable.

## 5. Prepared Datasets and Integration Format

### 5.1 Public dataset

`data/cleaned/public_esg_baseline.csv` contains **12,767 metric records**: 12,765 BCA observations and two SGX disclosures. A record represents one metric for one entity and year. It is not a count of unique buildings, because the same building can have several metrics and reporting years.

Cleaned numeric values are rounded to six decimal places and floor area to two. The original BCA files remain available for inspection at their original precision.

### 5.2 Private sample

`data/samples/private_esg_sample.csv` contains **34 synthetic records** for eight Alpha assets and one Beta asset. It uses the same columns as the public dataset. The raw fields show example inputs, while the standardised fields show the expected cleaned results.

| Example | Purpose |
| --- | --- |
| Alpha 01 | Ordinary office values |
| Alpha 02 | Different compatible units and expected conversions |
| Alpha 03 | Energy conversion with missing carbon and water values |
| Alpha 04 and 05 | Hotel and hospital property types |
| Alpha 06 | A common-area measurement boundary |
| Alpha 07 | An unsupported energy unit |
| Alpha 08 | A data-centre type with insufficient public peers |
| Beta | A second tenant label for backend privacy testing |

All these values are fabricated. Tenant labels allow the backend team to prepare isolation tests, but the labels themselves do not enforce privacy. The private sample is an integration example rather than a completed user-upload feature.

### 5.3 Shared record structure

The public dataset and the current private sample contain the same **20 columns**. This is a proposed data interface for the analytics team to review and map into its own implementation.

| Field | Description |
| --- | --- |
| `tenant_id` | `PUBLIC` for public data, or the organisation identifier for private data |
| `visibility` | `PUBLIC_BASELINE` or `PRIVATE_TENANT` |
| `entity_id` | Source-specific building or portfolio identifier |
| `postal_code` | Singapore postal code, stored as text to preserve leading zeroes; empty for the global portfolios |
| `entity_name` | Building or portfolio name |
| `property_type` | Standardised source building type |
| `region` | `SG` or `GLOBAL_MIXED` in the current dataset |
| `reporting_scope` | `ASSET` or `PORTFOLIO` |
| `reporting_year` | Year containing the reporting period end |
| `period_start` | First date covered |
| `period_end` | Last date covered |
| `gross_floor_area_sqm` | Building floor area in m²; empty where not established |
| `metric_code` | Metric identifier from the dictionary |
| `raw_value` | Original number or rating text; input EUI for a derived carbon record |
| `raw_unit` | Original unit, or `rating` for certification text |
| `standardised_value` | Cleaned or converted value; empty if unavailable |
| `canonical_unit` | Standard unit defined for the metric |
| `comparability_status` | The cleaning or comparison status described in Section 4 |
| `operational_boundary` | The building area or operational coverage measured |
| `source_reference` | Link to a BCA source, SGX register entry or synthetic example. Derived carbon references also identify the factor and its status |

An empty field means unavailable, not zero. Identifiers are specific to a source snapshot; they do not automatically link the same building across different BCA releases. The real tenant identifier must be obtained from authentication by the backend, rather than trusted from an uploaded file.

### 5.4 Utility calculation examples

`data/samples/utility_calculation_examples.csv` contains three synthetic cases with electricity, gas, diesel and floor-area inputs. Each case provides expected Scope 1 emissions, electricity-related Scope 2 estimates, energy intensity and carbon intensity. These examples support the Preliminary Report's TC-2 calculation evaluation.

The calculations use:

```text
Scope 1 (tonnes) = (gas kWh × gas factor + diesel litres × diesel factor) / 1,000
Scope 2 proxy (tonnes) = electricity kWh × grid factor / 1,000
Electricity EUI = electricity kWh / floor area in m²
Total energy intensity = (electricity kWh + gas kWh + diesel litres × diesel energy factor) / floor area
Carbon intensity = emissions in tonnes × 1,000 / floor area in m²
```

The fuel factors are explicit test assumptions: 10 kWh per litre of diesel, 2.68 kgCO2e per litre of diesel and 0.184 kgCO2e per kWh of gas. The total-energy calculation is not presented as the official BCA Mandatory Energy Improvement (MEI) definition. These examples are not independently certified audit spreadsheets.

### 5.5 Retained integration drafts

The folder also contains `data/test_fixtures/tenant_alpha_raw_upload.csv`, `data/test_fixtures/tenant_beta_isolation_test.csv` and `schemas/analytics_output_contract.json`. They are earlier upload, isolation and API-format drafts.

These files are not read or checked by `prepare_data.py`. They contain earlier field layouts, regional labels or metric definitions. For example, the Beta draft uses `CARBON_INTENSITY`, while the current sample uses `CARBON_INTENSITY_SCOPE2`. The integration team must align these drafts before using them with the current dataset. The current shared data interface is the 20-column structure above; the API response structure remains a separate team decision.

## 6. Data Availability and Limitations

The main limitations are limited public coverage and differences in measurement definitions. Public water peers are not supplied. Certification data are available only from the older BCA snapshot. The two SGX observations are too limited and differently defined to establish a compatible portfolio benchmark.

The carbon estimates depend on grid-factor versions and include a provisional 2025 factor. They do not measure the full emissions of a building. Source-specific building identifiers also mean that reliable comparisons of the same building across releases require further identity matching.

No source-backed 2030 targets have been configured. Historical top-quartile energy values should not be presented as net-zero targets. Where suitable peers or targets are missing, the analytics module should report that the result is unavailable.

## 7. User Requirements

The Preliminary Report identifies the following needs.

| User group | Requirement |
| --- | --- |
| Public evaluator or Free-tier user | Browse selected public data and understand the source, reporting period and coverage |
| Analyst, property manager or Professional-tier user | Upload private information, review standardisation and identify performance or disclosure gaps |
| Any organisation supplying private information | Keep its records separate from other organisations and public data |
| Enterprise team | Use API integration, collaboration, custom reporting and evidence-based AI explanations |

The prepared datasets support these planned workflows by supplying clear units, dates, sources and status labels. They do not establish that the application workflows have been implemented successfully.

The Preliminary Report's numerical discrepancy below 0.01%, calculation latency below 500 ms, uploads above 10 MB, zero unauthorised tenant access, user task completion of at least 90%, System Usability Scale score of at least 75 and AI trust score of at least 4/5 are evaluation targets. Local data preparation does not demonstrate these system-level results.

## 8. Competitor Analysis

The competitor review places the proposed prototype alongside existing real-estate sustainability and disclosure tools.

| Platform or approach | Documented capability | Implication for SPIP |
| --- | --- | --- |
| [GRESB](https://www.gresb.com/benchmark-report/) | Sustainability benchmarking and performance reports for real-estate organisations | SPIP offers a smaller prototype with visible source data and local comparison rules |
| [Measurabl](https://www.measurabl.com/) | Property sustainability data management and benchmarking, including a free offering | Benchmarking and free access alone are not unique SPIP features |
| [Deepki Index](https://www.deepki.com/solutions/deepki-index/) | Published energy and carbon benchmarks by geography and property type | SPIP's proposed distinction is its specific Singapore dataset and transparent prototype workflow |
| [SGX ESGenome](https://links.sgx.com/FileOpen/2022-09-12-ESGenome%20press%20release-SGX-FINAL.ashx?App=Announcement&FileID=731313) and [MAS Gprnt](https://www.mas.gov.sg/news/media-releases/2023/mas-launches-digital-platform-for-seamless-esg-data-collection-and-access) | ESG disclosure and data infrastructure | These provide context for reporting and data access; no claim is made that they lack analytics |
| In-house spreadsheets | A manual workflow that the project can compare against | Time savings and error reductions need to be measured through the planned user study |

Pricing, setup effort and detailed Singapore coverage have not been independently tested. The proposed value of SPIP is a small, reproducible Singapore-focused workflow. Its business advantages remain proposals to evaluate, rather than proven results.

## 9. Reproduction and Verification

### 9.1 Reproducing the public dataset

The required packages are listed in `requirements.txt`; their dependencies are installed automatically. The file allows version ranges, so a future installation may select different versions from this tested environment.

From the project folder, the dataset can be rebuilt with:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python prepare_data.py
```

For the tested dataset, the script reports:

```text
Saved 12,767 public records to <project folder>/data/cleaned/public_esg_baseline.csv
Checked 34 synthetic private records; no analytics or database operations were run.
```

The script reads local files and writes the public CSV. It checks the current private sample's structure but does not regenerate that sample or independently recalculate its expected values. It does not change source files, download new data or run a database. Installing packages requires access to the packages or a suitable local cache; rebuilding after installation uses only local data.

The script's input and output paths are based on its own location. To run it from another working folder, the Python interpreter and script must therefore be given their full paths. The following example starts in the project folder:

```sh
spip_project_dir="$PWD"
cd /tmp
"$spip_project_dir/.venv/bin/python" "$spip_project_dir/prepare_data.py"
```

### 9.2 Verification results

The following checks were performed. File hashes were recorded before running the commands and compared afterwards. A file hash identifies the exact file contents, allowing changes to be detected.

| Check | Result |
| --- | --- |
| Fresh environment setup | All packages installed successfully and the dependency check reported no broken requirements |
| Rebuild in the project folder | Completed successfully and produced the expected public dataset |
| Rebuild in the fresh temporary project copy | Produced a byte-for-byte identical public CSV |
| Rebuild from another working folder | Completed successfully and produced the same public CSV |
| Source and sample preservation | All source files, sample files and the metric dictionary retained their original hashes from before these runs |
| Output structure | Confirmed 12,767 public rows and 34 private sample rows, each with the same 20 columns; metadata and duplicate checks passed |
| Public carbon calculations | Independently recalculated all 5,965 derived carbon values using their reporting-year factors; all agreed within an absolute tolerance of 0.000001 |
| SGX observations | Both records matched their source-register entries, conversion rules, reporting dates and measurement boundaries |
| Certification and cleaning rules | Checked the rating mappings, 247 missing certifications, laboratory isolation, zero and near-zero readings, negative readings, high readings and combined-metering placeholders |
| Private sample values | Independently recalculated all 28 available values; the remaining six records retained their missing-data or anomaly status |
| Utility calculation examples | Recalculated 21 expected values across the three examples; the largest relative discrepancy was approximately 0.000000214%, below 0.01% |
| Rejection checks | Confirmed that unknown metric codes, incorrect standard units, incomplete annual periods and duplicate records were rejected |

The verified public CSV had the following SHA-256 file hash:

```text
b8987f00c6a1d7627279286365fd13ded32c9374e7e3630a74169fd895dbf662
```

The hash is a reference for this dataset and tested environment. It should change if the source data or preparation rules are deliberately updated.

These results verify the local preparation workflow and the numerical consistency of the supplied examples. They do not independently verify the source disclosures, certify an ESG audit, demonstrate production analytics accuracy or establish privacy enforcement or cloud performance. The earlier integration drafts described in Section 5.5 remain outside the preparation script's checks.
