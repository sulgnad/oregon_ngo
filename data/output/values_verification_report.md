# Values Verification Report

**Date:** 2026-05-26
**Source:** `data/output/orgs.csv`
**Tool:** `tests/test_verify_values.py`

## Overview

Verified that the text stored in the `values` column of `orgs.csv` can be found on the corresponding organization's website. The check fetches each site's homepage, `mission_source_url`, and common sub-pages (`/about`, `/about-us`, `/mission`, `/our-values`), then performs a normalized full-text comparison.

## Summary

| Metric           | Count |
|------------------|-------|
| Rows checked     | 51    |
| Links OK         | 51    |
| Links failed     | 0     |
| Values verified  | 33    |
| Values not found | 18    |

## Verified (33 rows)

All website links loaded successfully, and the full values text was located on the site:

- Black Parent Initiative (thebpi.org/about/)
- Blanchet House (blanchethouse.org/about)
- Carry It Forward (carryitforward.net/what-we-do)
- Clackamas Women's Services (cwsor.org/about-us/)
- Community Services Consortium (communityservices.us/about/)
- Confederated Tribes of Grand Ronde (grandronde.org)
- Direction Service (directionservice.org/mission)
- Doula Love Training Center (portlanddoulalove.com)
- Dove Advocacy Center (lakecountycrisiscenter.org)
- El Programa Hispano Católico (elprograma.org)
- Eugene Mission (eugenemission.org/about)
- FinAbility (finability.org)
- Hearts with a Mission (heartswithamission.org/about/)
- Hope & Safety Alliance (hopesafetyalliance.org)
- HousingWorks (housing-works.org/about/)
- Jackson Street Youth Services (jacksonstreet.org/about/)
- Maslow Project (maslowproject.com/about-us)
- MWVCAA – ARCHES Project (mwvcaa.org)
- Mid-Willamette Valley Homeless Alliance (mwvhomelessalliance.org)
- OHRA (ohrahelps.org)
- Olive Plaza / HumanGood (humangood.org/about)
- Parenting With Intent (parentingwithintent.org)
- Path Home (path-home.org/mission-and-vision)
- Raphael House of Portland (raphaelhouse.com)
- REACH (reachoutcentraloregon.org/about-us/)
- Rogue Retreat (rogueretreat.org/about)
- Saving Grace (saving-grace.org/about)
- Self-Enhancement, Inc. (selfenhancement.org/about)
- SASS (sass-lane.org/mission-values/)
- Shelter from the Storm (unioncountysfs.org)
- Shepherd's House Ministries (shepherdshouseministries.org)
- Transition Projects (tprojects.org/story)
- Union Gospel Mission of Salem (ugmsalem.org/about-us)

## Not Found — Duplicate Rendering in CSV (9 rows)

The values text **does exist** on the website, but the scraper captured each value 2–3× due to CSS/JS rendering artifacts. The website lists each value once, so the duplicated string in the CSV cannot match verbatim.

| Row | Organization | Notes |
|-----|-------------|-------|
| 10  | Bradley Angle | Each value repeated 2–3×; footer text also captured |
| 29  | Community Supported Shelters | "Button" UI elements interspersed in scraped text |
| 45  | Family Promise of the Mid-Willamette Valley | Each value repeated 3× |
| 88  | NeighborImpact | Entire values block duplicated |
| 94  | Northwest Human Services (HOAP) | Each value duplicated |
| 117 | Rose Community Development | Entire values block duplicated |
| 135 | Street Roots | Entire values block duplicated |
| 140 | Thrive Central Oregon | Each value repeated 3× |
| 148 | Women's Crisis Support Team (WCST) | Each value duplicated |

**Recommendation:** De-duplicate the `values` field for these rows so it contains each value statement exactly once.

## Not Found — Website Content Changed (9 rows)

The specific values text no longer appears on any checked page. The site has been updated or redesigned since the scrape on 2026-05-05.

| Row | Organization | Details |
|-----|-------------|---------|
| 5   | Bethlehem Inn | Compassion/Equity/Empowerment values section not found |
| 16  | Catholic Charities of Oregon | About page rewritten; "Catholic Social Teaching" paragraph replaced |
| 19  | Central City Concern | "Our values are the principles…" no longer on homepage |
| 37  | Do Good Multnomah | Site fully redesigned; detailed values section removed |
| 56  | HAVEN from Domestic and Sexual Violence | Redesigned; "roots of violence" quote replaced with new values list |
| 108 | Portland Rescue Mission | "Mobile Outreach Ministry" text removed; site redesigned |
| 125 | SARC | Text appears to be on the page; likely fails due to character encoding differences (em dashes, special chars) |
| 147 | WellMama | Site redesigned; beliefs section no longer present |
| 149 | YWCA of Greater Portland | "diverse lived experience" phrase not on current site |

**Recommendation:** Re-scrape values for these 9 organizations. SARC (row 125) may only need an encoding fix.

## Reproducing This Report

Run the verification tool on demand:

```sh
# Via pytest (per-org pass/fail output):
pytest tests/test_verify_values.py -m live -v

# Via CLI (summary report):
python -m tests.test_verify_values
python -m tests.test_verify_values path/to/other.csv
```
