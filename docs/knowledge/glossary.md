# Real Estate Terminology Glossary

Definitions match how these terms are computed in this project's own agents
(`market-stats`, `recommendation`) wherever applicable, not just generic
industry usage.

**DOM (Days on Market)** — The number of days a listing has been actively for
sale, from list date to either the current date (active listing) or the date
it went under contract (sold listing). In `rets_property` this is
`DaysOnMarket` as of the data pull; in `california_sold` it's
`DaysOnMarket`, the days from listing to accepted offer. Lower DOM generally
signals a hotter market or a more competitively priced/desirable property.

**Comps (Comparable Sales)** — Recently sold properties similar in location,
size, and features to a subject property, used to estimate its fair market
value. This project's `recommendation` skill validates an active listing's
price against comps in `california_sold` — sold homes in the same city with
living area within ±20% of the subject, closed in the trailing 6 months.

**List-to-Close Ratio** — The final close price as a percentage of the list
price at the time of contract: `ClosePrice / ListPrice * 100`. A ratio near
or above 100% signals a seller's market (buyers bidding at or above ask); a
ratio noticeably below 100% signals a buyer's market (sellers conceding on
price). Computed in `market_stats.get_city_stats()` as `list_to_close_pct`.

**Price per Square Foot ($/sqft)** — Close price (or list price) divided by
living area, used to compare properties of different sizes on a common
basis and to estimate a fair price for a given square footage from
comparable sales. Computed as `ClosePrice / LivingArea` in the market and
recommendation agents.

**Cap Rate (Capitalization Rate)** — For investment/rental property, annual
net operating income divided by property value or purchase price, expressed
as a percentage. A quick measure of expected return independent of
financing. Not currently computed by any agent in this project (no rental
income field in either MLS table), but relevant vocabulary for investment
property questions.

**Escrow** — A neutral third-party arrangement that holds funds and
documents during a real estate transaction until all contract conditions
are met, then disburses funds and records the transfer. Distinct from the
listing/sale data tracked in `california_sold`, which records the outcome
(`ClosePrice`, `CloseDate`) rather than the escrow process itself.

**Contingency** — A condition in a purchase contract that must be satisfied
for the deal to proceed (e.g., financing, appraisal, inspection, sale of the
buyer's current home). If a contingency isn't met, the buyer can typically
cancel and recover their earnest money deposit.

**Earnest Money Deposit (EMD)** — A good-faith deposit a buyer submits with
an offer to demonstrate serious intent to purchase; applied toward the down
payment/closing costs at close, or forfeited/returned depending on how the
deal ends and which contingencies were in play.

**HOA (Homeowners Association) Fee** — A recurring fee paid by owners in a
community with shared amenities or maintained common areas, covering
upkeep, insurance, and sometimes utilities. Tracked as `AssociationFee` in
both MLS tables; amenities covered are listed in `AssociationAmenities`.

**MLS (Multiple Listing Service)** — A regional database where real estate
brokers share property listing information, the primary system of record
this project's two tables (`rets_property`, `california_sold`) are sourced
from.

**RESO (Real Estate Standards Organization)** — The industry body that
defines standardized field names and data formats for MLS data exchange
(the "RESO Data Dictionary"). `rets_property.StandardStatus` uses
RESO-standard status values (Active, Pending, Closed) alongside the
system's native `L_Status` field.

**Pending** — A listing status meaning the seller has accepted an offer and
the transaction is in progress (inspections, financing, etc.) but hasn't
closed yet. Distinct from Active (still accepting offers) and Closed/Sold
(transaction complete, appears in `california_sold`).

**Original List Price vs. List Price** — `OriginalListPrice` is the price a
property was first listed at; `ListPrice` is the price at the time an offer
was accepted, which may be lower after price reductions
(`rets_property.PreviousListPrice` tracks the prior price on an active
listing for the same reason).

**Living Area / Square Footage** — The finished, livable interior square
footage of a home, excluding garages, unfinished basements, and outdoor
space. `LM_Int2_3` in `rets_property`, `LivingArea` in `california_sold`.

**Lot Size** — The size of the land parcel a property sits on, tracked in
both acres (`LotSizeAcres`) and square feet (`LotSizeSquareFeet`), distinct
from living area (the size of the structure).

**APN (Assessor's Parcel Number)** — A unique identifier a county assessor's
office assigns to a specific parcel of land for property tax and record
purposes. Tracked as `ParcelNumber` in `rets_property`.
