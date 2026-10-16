## 1. Metric Dictionary

SPIP automatically harmonises heterogeneous ESG disclosures into a standardized canonical representation stored in the `Standardised_ESG_Records` PostgreSQL table.   

| **Metric Code**        | **Metric Name**                      | **Canonical Unit**                    | **Supported Input Units & Conversion Logic**                 | **Performance Direction** | **Compatible Scopes** | **Primary Source**             |
| ---------------------- | ------------------------------------ | ------------------------------------- | ------------------------------------------------------------ | ------------------------- | --------------------- | ------------------------------ |
| `CARBON_INTENSITY`     | Carbon Emissions Intensity           | $\text{kgCO}_2\text{e}/m^2/\text{yr}$ | $\text{tCO}_2\text{e}/m^2$ ($\times 1000$), $\text{gCO}_2\text{e}/m^2$ ($\div 1000$), $\text{kgCO}_2\text{e}/\text{sq ft}$ ($\times 10.7639$), or derived via $\text{EUI} \times \text{EMA Grid Emission Factor}$ | `LOWER_IS_BETTER`         | `ASSET`, `PORTFOLIO`  | SGX Reports / BCA EUI derived  |
| `SCOPE_1_EMISSIONS`    | Direct GHG Emissions                 | $\text{tCO}_2\text{e}$                | $\text{kgCO}_2\text{e}$ ($\div 1000$), $\text{ktCO}_2\text{e}$ ($\times 1000$) | `LOWER_IS_BETTER`         | `ASSET`, `PORTFOLIO`  | SGX / Tenant Utility Upload    |
| `SCOPE_2_EMISSIONS`    | Indirect GHG Emissions (Electricity) | $\text{tCO}_2\text{e}$                | $\text{kgCO}_2\text{e}$ ($\div 1000$), $\text{MWh}$ ($\times \text{EMA Grid Emission Factor}$, e.g., $0.412\text{ tCO}_2\text{e/MWh}$) | `LOWER_IS_BETTER`         | `ASSET`, `PORTFOLIO`  | SGX / Tenant Utility Upload    |
| `ENERGY_INTENSITY_EUI` | Energy Use Intensity (EUI / MEI)     | $\text{kWh}/m^2/\text{yr}$            | $\text{MWh}/m^2$ ($\times 1000$), $\text{GJ}/m^2$ ($\times 277.778$), $\text{kWh}/\text{sq ft}$ ($\times 10.7639$) | `LOWER_IS_BETTER`         | `ASSET`, `PORTFOLIO`  | BCA BEBR / SGX / Tenant Upload |
| `WATER_INTENSITY`      | Water Use Intensity                  | $m^3/m^2/\text{yr}$                   | $\text{Litres}/m^2$ ($\div 1000$), $\text{ML}/m^2$ ($\times 1000$) | `LOWER_IS_BETTER`         | `ASSET`, `PORTFOLIO`  | SGX / Tenant Upload            |
| `GREEN_CERT_LEVEL`     | BCA Green Mark Certification         | Ordinal Score ($0\text{–}4$)          | String mapping: `Uncertified`=0, `Certified` / `Legislated`=1, `Gold`=2, `GoldPlus`=3, `Platinum` / `Super Low Energy`=4 | `HIGHER_IS_BETTER`        | `ASSET`               | BCA Green Mark Directory       |
| `GREEN_PORTFOLIO_PCT`  | Green Certified Floor Area %         | `%` ($0\text{–}100$)                  | Decimal ratio $0\text{–}1$ ($\times 100$), Certified GFA $\div$ Total GFA | `HIGHER_IS_BETTER`        | `PORTFOLIO`           | SGX Sustainability Reports     |

## 2. Public Datasets & Observations

Two primary public baseline sources:

1. **BCA Building Energy Submission System (BESS) Reports:**
   - `Listing of Building Energy Performance Data 2020.csv`: 564 commercial assets spanning 2017–2020 EUI, providing historical trajectory and Green Mark certification ratings.   
   - *`bca-bebr-data.xlsx`:* 997 assets spanning 2022–2025 EUI, Gas Use Intensity (GUI), and functional GFA breakdowns across 15 building types.   
2. **SGX S-REIT & Developer Baseline (`sgx_reit_public_baseline.csv`):**
   - Curated portfolio-level disclosures for 15 major Singapore REITs (FY2023–FY2024).

### Real-World Data Anomalies Handled by Ingestion Pipeline:

- **Negative Billing Adjustments:** Outlier checks flag observations with $\text{EUI} \le 0$ (e.g., retrofitted utility rebates such as `-372.20 kWh/m²/yr`) as `ANOMALY_FLAGGED`.   
- **Pre-Operational Zero Values:** Newly developed assets reporting `0` EUI prior to opening are mapped to `INCOMPLETE_DATA` (`NULL`) rather than `0.0` to prevent skewing peer percentiles.   
- **Special-Use Outliers:** Research labs and cleanrooms (e.g., Institute of Microelectronics at $>2,200\text{ kWh}/m^2/\text{yr}$) are isolated from standard commercial benchmarking cohorts.

## 3. Data Availability & Limitations

- **Granularity Mismatch (Asset vs. Portfolio):** BCA reports at the individual building level, whereas SGX S-REIT reports aggregate utility use at the corporate portfolio level. *Mitigation:* Explicit `reporting_scope` tagging (`ASSET` vs. `PORTFOLIO`) in the schema.   
- **Accounting Boundary Discrepancies:** Variations in Location-based vs. Market-based Scope 2 accounting and landlord vs. tenant-controlled boundaries. *Mitigation:* Incompatible records are tagged with `comparability_status = 'BOUNDARY_MISMATCH'` and excluded from medians.   
- **Reporting Lag:** Public datasets are published with a 4–9 month lag, requiring clear labeling of baseline reporting years.

## 4. User Requirements by Subscription Tier

- **Free Tier (Public Evaluators):** Read-only access to public BCA/SGX baseline medians and basic asset searches.   
- **Professional Tier (ESG Analysts / Property Managers):** Bulk CSV/XLSX uploads (>10 MB via S3 presigned URLs), automated unit conversion, empirical percentile ranking, and gap analysis against 2030 net-zero targets.   
- **Enterprise Tier (REITs / Major Developers):** Multi-tenant workspace isolation via PostgreSQL Row-Level Security (RLS), API ingress, and Amazon Bedrock AI assistant integration.   

## 5. Competitor Analysis Matrix

| **Platform / Solution**   | **Primary Focus**                            | **Key Limitations for Singapore Real Estate**                | **How SPIP Differentiates**                                  |
| ------------------------- | -------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| **GRESB**                 | Global institutional ESG benchmark for funds | Annual submission cycle; high membership cost; slow feedback loops | Instant, on-demand self-service asset & portfolio benchmarking with transparent empirical percentiles |
| **Measurabl / Deepki**    | Enterprise real estate ESG data management   | Heavy enterprise onboarding; closed proprietary peer benchmarks; expensive for mid-sized managers | Lightweight multi-tenant SaaS with out-of-the-box Singapore BCA & SGX baseline datasets |
| **SGX ESGenome**          | Regulatory compliance disclosure portal      | Designed for compliance entry, not automated asset-level energy/carbon analytics | Automates unit harmonisation, rule-based fallback cohorts, and 2030 net-zero gap quantification |
| **In-House Spreadsheets** | Ad-hoc manual tracking                       | Error-prone unit conversions; fragmented files; high annual update effort | Automated ingestion pipeline (`<0.01%` discrepancy) cutting workflow time with `>=90%` task efficiency |