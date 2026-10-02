# Candidate data sources

> **Unverified.** This is a research checklist, not a validated source list. Every entry
> needs a human to confirm the organization still exists, still does what's described, and
> to capture a canonical URL before it enters `data/`. Some of these may be defunct,
> renamed, or merged — Richmond's nonprofit landscape has churned. Treat anything below as
> "go look this up", and record the outcome in the Status column.

Status values: `todo` → `verified` (URL captured, record written) | `dead` (defunct/404) |
`merged` (into another entry) | `skip` (out of scope).

**See also `resources.csv`** in the repo root — a hand-maintained list of ~15 organizations
that already has URLs and descriptions, covering volunteering, native plants, food waste,
reuse, and greener-alternative resources. It is the more trustworthy of the two documents
because a person compiled it deliberately; this file is the gap-filling research list, and
it skews toward the waste-disposal questions the CSV doesn't cover. Entries below that
duplicate a CSV row should be marked `merged`. Import rules and cleanup notes:
`PLAN.md` §3d.

## Tier 1 — official, authoritative

These should be the backbone of the corpus. Prefer these over any secondhand summary, and
check whether each publishes an open-data endpoint or API before scraping HTML.

| Source | What it should cover | Jurisdiction | Status |
| --- | --- | --- | --- |
| Central Virginia Waste Management Authority (CVWMA) | Regional curbside recycling program, accepted-items list, drop-off centers, glass, HHW and electronics events | regional | todo |
| City of Richmond — Public Works / Public Utilities | Trash & recycling collection, bulk pickup, leaf collection, stormwater, water utility programs | richmond-city | todo |
| Henrico County — Public Works / Public Utilities | Collection rules, convenience centers, HHW | henrico | todo |
| Chesterfield County — equivalent departments | Collection rules, convenience centers, HHW | chesterfield | todo |
| Hanover County — equivalent departments | Collection rules, convenience centers | hanover | todo |
| RVAgreen 2050 (city climate action plan) | Climate goals, equity framing, program inventory | richmond-city | todo |
| RVAH2O (combined sewer overflow program) | Why stormwater/sewer guidance matters locally | richmond-city | todo |
| Virginia DEQ | State recycling rates, regulated waste, permits, grants | virginia | todo |
| Virginia Dept. of Energy | State energy programs, weatherization | virginia | todo |
| Dominion Energy | Efficiency rebates, EnergyShare-type assistance, net metering, renewable options | virginia | todo |
| GRTC | Fares, passes, routes, any fare-free status | regional | todo |
| Virginia Dept. of Health / DEA take-back | Medication disposal, sharps | virginia | todo |

## Tier 2 — specific disposal streams

The highest-traffic questions. Each needs a confirmed, current drop-off answer.

| Stream | Likely answer path to verify | Status |
| --- | --- | --- |
| Rechargeable / lithium-ion batteries, power banks, vapes | Call2Recycle partner retailers (hardware/battery/office stores), CVWMA events | todo |
| Alkaline (AA/AAA) batteries | Often landfill-acceptable in VA — **confirm current local guidance**, don't assume | todo |
| Car / lead-acid batteries | Auto parts retailers (core charge/takeback) | todo |
| Electronics, laptops, CRT TVs | County convenience centers, CVWMA events, certified e-recyclers, retailer takeback | todo |
| Paint (latex vs. oil-based) | PaintCare-style programs if active in VA; HHW events otherwise | todo |
| Motor oil, antifreeze, filters | Auto parts retailers, HHW | todo |
| Propane tanks, fire extinguishers | Exchange programs, HHW, scrap metal | todo |
| Fluorescent tubes / CFLs | Hardware retailer takeback, HHW | todo |
| Tires | County sites, tire retailers | todo |
| Mattresses, furniture, appliances | Bulk pickup rules, scrap metal, reuse orgs | todo |
| Medications & sharps | Police station drop boxes, pharmacy kiosks, take-back days | todo |
| Cooking oil / grease | Transfer stations, biodiesel collectors | todo |
| Textiles & shoes | Thrift/reuse orgs, textile recyclers | todo |
| Styrofoam, plastic film/bags | Usually *not* curbside — find the actual local option | todo |
| Glass | Regional glass handling is a known gotcha — get this exactly right | todo |
| Yard waste & Christmas trees | Seasonal municipal programs | todo |

## Tier 3 — composting

| Source | Notes | Status |
| --- | --- | --- |
| Subscription curbside compost haulers serving the metro | Identify who currently operates here, service areas, pricing | todo |
| Commercial/industrial composters accepting residential drop-off | | todo |
| Farmers-market or community drop-off points | | todo |
| Virginia Cooperative Extension / master gardeners | Home composting guidance, soil testing | todo |

## Tier 4 — get involved (nonprofits, volunteering)

Highest churn risk — verify each before writing a record.

| Organization | Likely focus | Status |
| --- | --- | --- |
| Groundwork RVA | Youth, green infrastructure | todo |
| Friends of James River Park | River park stewardship, cleanups | todo |
| James River Association | River health, volunteer programs | todo |
| Capital Trees | Urban greening downtown | todo |
| Richmond Tree Stewards / city tree planting programs | Tree planting, pruning | todo |
| Shalom Farms | Food access, urban agriculture | todo |
| Tricycle / urban agriculture orgs | Community gardens | todo |
| Sierra Club — Falls of the James group | Advocacy | todo |
| Keep Virginia Beautiful / Clean Virginia Waterways | Litter, cleanups, grants | todo |
| Blue Sky Fund | Outdoor education | todo |
| Bike Walk RVA / Sports Backers | Active transportation advocacy | todo |
| Solar United Neighbors (Virginia) | Solar co-ops, homeowner guidance | todo |
| Virginia Clean Cities | Alternative fuels, EV | todo |
| Community garden networks | Plot availability | todo |
| Enrichmond Foundation | **Known to have dissolved — verify and likely mark `dead`**, and check what absorbed its programs | todo |

## Tier 5 — reuse & repair

| Organization | Notes | Status |
| --- | --- | --- |
| Habitat for Humanity ReStore | Building materials, appliances | todo |
| Diversity Thrift | General donation | todo |
| CARITAS / furniture bank-type programs | Furniture donation with pickup | todo |
| Goodwill of Central Virginia | General donation, some e-waste | todo |
| Tool library / lending library | Borrowing instead of buying | todo |
| Repair cafés / fix-it clinics | Recurring events | todo |
| Creative-reuse / scrap art organizations | Craft materials | todo |
| Local bike co-op / refurbishers | Bike donation & repair | todo |

## Tier 6 — energy, water, home

| Source | Notes | Status |
| --- | --- | --- |
| Income-qualified weatherization providers serving the metro | Free/subsidized efficiency upgrades | todo |
| Utility bill assistance programs | Eligibility and application path | todo |
| Rain barrel / stormwater incentive programs | Rebates, workshops | todo |
| Solarize-type group purchase programs | Current availability in VA | todo |
| Local HVAC/insulation rebate aggregators | Cross-check against federal credits | todo |
| Federal residential energy credits (IRS) | Changes with tax law — date-stamp carefully | virginia/federal, todo |

## Collection notes

- **Snapshot everything** into `data/raw/` with a fetch date. Pages get rewritten; the
  snapshot is what makes a content diff reviewable.
- **Check `robots.txt`**, identify the crawler honestly, and rate-limit to single-digit
  requests per minute. Nothing here is time-critical.
- **PDFs are common** in municipal waste guidance — budget for PDF text extraction.
- **Prefer a phone call** over a scrape for hours and accepted items on the top ~25
  entities. One afternoon of calls produces better data than any pipeline.
- **Record `last_verified` and `verified_by`** on every entity, always. An answer without a
  verification date is a liability.
