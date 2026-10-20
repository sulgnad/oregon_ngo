# Benton, Columbia and Coos counties — final data report
**Generated:** 2026-10-19
**Data collected:** 2026-10-12; hand-verified seed values as of generation
**Scope:** domestic and sexual violence, housing and maternal health resources with a physical office in the county. Nonprofit, government and tribal programs; for-profit providers are excluded.

## Deliverables
| File | Contents |
|---|---|
| `focus_counties_snmp.csv` | 39 rows in the Map Database layout: the 28 sheet columns plus Organization_ID and Location_ID |
| `focus_counties_snmp_organizations.csv` | Organization table, workbook layout |
| `focus_counties_snmp_locations.csv` | Location table, workbook layout |
| `focus_counties_validation.csv` | One row per organization: where each value came from, gaps and flags |

All files are in `data/output/`, next to this report.

## Headline numbers
| County | Orgs | Street address | PO Box only | Phone | Email | Website | Summary | All five fields | Verified |
|---|---|---|---|---|---|---|---|---|---|
| Benton County | 16 | 15/16 (94%) | 1 | 15/16 (94%) | 12/16 (75%) | 16/16 (100%) | 16/16 (100%) | 10/16 (62%) | 13/16 (81%) |
| Columbia County | 9 | 8/9 (89%) | 1 | 9/9 (100%) | 6/9 (67%) | 9/9 (100%) | 9/9 (100%) | 6/9 (67%) | 9/9 (100%) |
| Coos County | 14 | 14/14 (100%) | 0 | 14/14 (100%) | 8/14 (57%) | 14/14 (100%) | 14/14 (100%) | 8/14 (57%) | 12/14 (86%) |
| **Total** | 39 | 37/39 (95%) | 2 | 38/39 (97%) | 26/39 (67%) | 39/39 (100%) | 39/39 (100%) | 24/39 (62%) | 34/39 (87%) |

"All five fields" means street address, phone, email, website and summary are all filled. "Verified" means the name, website and contact details were confirmed in at least two independent public sources.

## By category
| Category | Benton | Columbia | Coos | Total |
|---|---|---|---|---|
| Housing & Shelter Assistance | 11 | 4 | 7 | 22 |
| Medical Care | 2 | 4 | 4 | 10 |
| Crisis Intervention & Advocacy Services | 3 | 3 | 3 | 9 |

An organization can appear in more than one category.

## By agency type and level
| Type / Level | Benton | Columbia | Coos | Total |
|---|---|---|---|---|
| Private / City | 10 | 6 | 6 | 22 |
| Public / County | 5 | 2 | 4 | 11 |
| Public / Tribal | 0 | 0 | 4 | 4 |
| Public / State | 1 | 1 | 0 | 2 |

## Integrity checks
| Check | Result |
|---|---|
| Column headers match the export layout | pass |
| Headers match SNMP_Main.xlsx | yes |
| Row counts agree across the flat, Organization, Location and JSONL files | pass |
| Every organization has a seed entry | pass (39/39) |
| Location_IDs are unique | pass |
| All IDs are deterministic UUIDv5 | pass |
| Every location points to an existing organization | pass |
| Every row reproduces exactly with the current export code | pass (39/39) |
| Organizations listed in more than one county | 0 |
| Websites load | pass (39/39) |

## Where the values come from
| Field | Hand-verified seed | Pipeline (website or IRS record) | Missing |
|---|---|---|---|
| Address | 37 | 2 | 0 |
| Phone | 38 | 0 | 1 |
| Email | 23 | 3 | 13 |

Summaries: 24 are the organization's own mission statement copied in by hand, 6 were extracted from the organization's own website, and 9 are written descriptions.

## Open issues
- **Unverified** (5): Benton County Coordinated Homeless Response Office (Benton); Community Services Consortium (Benton); DevNW (Benton); Circles of Healing (Coos); Coos County Crime Victims' Assistance (Coos)
- **PO Box only (Postal location)** (2): Harriet's Housing (Benton); SAFE of Columbia County (Columbia)
- **Email not hand-verified** (2): Oregon Coast Community Action (Coos); Waterfall Community Health Center (Coos)
- **Email not hand-verified (free-mail)** (1): South Coast Gospel Mission (Coos)

Missing fields: email 13, street address 2, phone 1.

## Research notes from the seed files
These are recorded as comments in the seed files and are not visible in the export.

| County | Organization | Note |
|---|---|---|
| Benton | Benton County Coordinated Homeless Response Office | **Funding Cliff:** CHRO's own August 2026 report to the Board of Commissioners and City Council projects Benton County shelter capacity falling from 157 beds to 48 by March 2027 absent new money. |
| Benton | Community Outreach, Inc. | **Move:** COI's own homepage states that Mari's Place, its childcare centre, moved to 2701 NW Satinwood St, Corvallis, from September 2026; the main campus address below is unchanged. |
| Benton | Community Services Consortium | **Address Moved:** hence "unverified". CSC's own contact page gives the Benton County regional office as 1121 NW 9th St, Corvallis (541-752-1010), while every third-party directory and CSC's own older resource guide still show 545 SW 2nd St Suite A. The current address rests on CSC's own site alone. |
| Benton | Corvallis Daytime Drop-in Center | **Address Conflict:** CDDC's own site gives 559 SW 4th St; Unity Shelter's referral page gives 530 SW 4th. The organization's own figure is used. |
| Benton | Good Samaritan Regional Medical Center | **Service Risk:** Samaritan's own "Exploring Services: Women & Children" page says obstetrics across its five hospitals runs at a large loss and that the service model will be reassessed in summer/autumn 2026. Deliveries are stated to continue at all five hospitals for now. |
| Benton | Linn-Benton Housing Authority | **Caution:** "lbha.org" is NOT this agency; that domain now serves a gambling site. The authority's domain is l-bha.org. |
| Benton | Oregon State University Center for Advocacy, Prevention & Education | **Name Change:** this service was the Survivor Advocacy and Resource Center (SARC) in Plageman 311; it is now the Center for Advocacy, Prevention & Education in Student Experience Center 350. Older OSU PDFs still say SARC. |
| Benton | Unity Shelter | **Service History:** Unity announced in May 2025 that funding losses would suspend the Men's Shelter, Room at the Inn and the Emergency Hotel Shelter from July 1 and cut about 80% of staff (Corvallis Gazette-Times / OregonLive, 11-12 May 2025). A combined shelter ran at Room at the Inn over the summer; the Men's Shelter reopened at Chapman Center on 9 December 2025, restoring 50 beds. Per Benton County's Coordinated Homeless Response Office (August 2026), the Emergency Hotel Shelter is funded only through October 2026 and the two congregate shelters only through March 2027. |
| Columbia | OHSU Primary Care Clinic, Scappoose | **Status:** OHSU said in January 2026 it was considering converting the clinic to a Federally Qualified Health Center. Clinic faculty and residents wrote to OHSU leadership opposing the change over reproductive-health access; OHSU said it remains committed to full-scope reproductive care in Columbia County. No conversion had been announced. |
| Columbia | SAFE of Columbia County | **No Street Address Is Recorded:** the organization publishes only PO Box 22, and the Oregon Secretary of State registry's "principal place of business" (2194 Columbia Blvd) is the South Columbia County Chamber of Commerce building, which other filings show is a shared registered-agent address -- not SAFE's office. The confidential shelter ("The Safe House" / "The Starting Place") is at an undisclosed location by design. |
| Coos | Bay Area Hospital | **Service Change:** the hospital discontinued its MOMS (Management of Maternity Services) program, including postpartum at-home visits, on 2025-02-09, and closed its Bright Beginnings childcare center on 2025-02-28. Childbirth classes, lactation consultation and post-discharge planning continue. |
| Coos | Oregon Coast Community Action | **Caution:** not reflected in the export: ORCCA's own 2026 board minutes, as reported by The World and the Curry Pilot (Aug-Sep 2026), document audits roughly four years behind, cash-flow concerns, and an unresolved question about $600,000 of Food Share grant money. On 2026-10-08 the board ended its oversight of the CASA program, pausing those services. The housing, weatherization and Head Start programs were still operating. |

## Organizations
### Benton County (16)
| Organization | Category | Type / Level | Verified | Gaps and flags |
|---|---|---|---|---|
| Benton County Coordinated Homeless Response Office | Housing & Shelter Assistance | Public / County | no | no phone |
| Benton County District Attorney Victim Assistance Program | Crisis Intervention & Advocacy Services | Public / County | yes | — |
| Benton County Health Department | Medical Care | Public / County | yes | — |
| Benton Habitat for Humanity | Housing & Shelter Assistance | Private / City | yes | — |
| Center Against Rape and Domestic Violence | Crisis Intervention & Advocacy Services | Private / City | yes | — |
| Community Outreach, Inc. | Housing & Shelter Assistance | Private / City | yes | — |
| Community Services Consortium | Housing & Shelter Assistance | Public / County | no | no email |
| Corvallis Daytime Drop-in Center | Housing & Shelter Assistance | Private / City | yes | — |
| Corvallis Housing First | Housing & Shelter Assistance | Private / City | yes | — |
| DevNW | Housing & Shelter Assistance | Private / City | no | no email |
| Good Samaritan Regional Medical Center | Medical Care | Private / City | yes | no email |
| Harriet's Housing | Housing & Shelter Assistance | Private / City | yes | no street address; PO Box only (Postal location) |
| Jackson Street Youth Services | Housing & Shelter Assistance | Private / City | yes | no email |
| Linn-Benton Housing Authority | Housing & Shelter Assistance | Public / County | yes | — |
| Oregon State University Center for Advocacy, Prevention & Education | Crisis Intervention & Advocacy Services | Public / State | yes | — |
| Unity Shelter | Housing & Shelter Assistance | Private / City | yes | — |

### Columbia County (9)
| Organization | Category | Type / Level | Verified | Gaps and flags |
|---|---|---|---|---|
| Columbia County District Attorney's Victims Assistance Program | Crisis Intervention & Advocacy Services | Public / County | yes | — |
| Columbia County Habitat for Humanity | Housing & Shelter Assistance | Private / City | yes | — |
| Columbia County Public Health | Medical Care | Public / County | yes | — |
| Columbia Health Services | Medical Care | Private / City | yes | — |
| Community Action Team, Inc. | Housing & Shelter Assistance, Medical Care | Private / City | yes | — |
| OHSU Primary Care Clinic, Scappoose | Medical Care | Public / State | yes | no email |
| Oregon Law Center - St. Helens Office | Crisis Intervention & Advocacy Services, Housing & Shelter Assistance | Private / City | yes | no email |
| SAFE of Columbia County | Crisis Intervention & Advocacy Services | Private / City | yes | no street address; no email; PO Box only (Postal location) |
| Turning Point Community Service Center | Housing & Shelter Assistance | Private / City | yes | — |

### Coos County (14)
| Organization | Category | Type / Level | Verified | Gaps and flags |
|---|---|---|---|---|
| Bay Area Hospital | Medical Care | Public / County | yes | no email |
| Circles of Healing | Crisis Intervention & Advocacy Services | Public / Tribal | no | no email |
| Confederated Tribes of Coos, Lower Umpqua and Siuslaw Indians Housing Department | Housing & Shelter Assistance | Public / Tribal | yes | no email |
| Coos County Crime Victims' Assistance | Crisis Intervention & Advocacy Services | Public / County | no | — |
| Coos Health & Wellness | Medical Care | Public / County | yes | no email |
| Coquille Indian Housing Authority | Housing & Shelter Assistance | Public / Tribal | yes | — |
| Ko-Kwel Wellness Center - Coos Bay | Medical Care | Public / Tribal | yes | — |
| NeighborWorks Umpqua | Housing & Shelter Assistance | Private / City | yes | no email |
| North Bend City / Coos-Curry Housing Authorities | Housing & Shelter Assistance | Public / County | yes | — |
| Oregon Coast Community Action | Housing & Shelter Assistance | Private / City | yes | email not hand-verified |
| South Coast Gospel Mission | Housing & Shelter Assistance | Private / City | yes | email not hand-verified (free-mail) |
| The Devereux Center | Housing & Shelter Assistance | Private / City | yes | no email |
| The SAFE Project | Crisis Intervention & Advocacy Services | Private / City | yes | — |
| Waterfall Community Health Center | Medical Care | Private / City | yes | email not hand-verified |

## Notes and limitations
- `Operations_Status` is always "Normal operations", so the service changes above are not reflected in the export.
- The 14 Map Database columns this tool can't fill from public sources (hours, eligibility, parent organization and so on) are left blank for manual entry.
- An address that is only a PO Box is exported as a Postal location: the Location table keeps the box, and the Map Database's `Primary_Location_Address` is blank because a box can't be mapped.
- `Org_Agency_Level` defaults to City for nonprofits, County for government and Tribal for tribal programs, unless a seed sets `agency_level`.
- Emails for government and tribal programs come only from the seed files; the pipeline does not scrape them from shared government websites.
- Websites were checked live on 2026-10-19. Servers that refuse this machine's Python TLS library were re-checked with curl.
