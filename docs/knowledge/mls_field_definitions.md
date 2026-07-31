# MLS Field Definitions

Column reference for the two MLS tables in the `idx_exchange` MySQL schema.
Both tables can be joined via `CAST(rets_property.L_ListingID AS UNSIGNED) =
california_sold.ListingKey`, or via city + postal code for market-level
analysis.

## rets_property — Active Listings

The live search and discovery table (~228K active California listings, 130+
fields).

| Column | Type | Description |
|---|---|---|
| `id` | INT PK | Auto-increment primary key |
| `L_ListingID` | VARCHAR | MLS system listing ID — joins to `california_sold.ListingKey` |
| `L_DisplayId` | VARCHAR | Human-readable MLS number shown on portals |
| `L_Address` | VARCHAR | Full street address |
| `L_City` | VARCHAR | City — indexed for fast city-based queries |
| `L_Zip` | VARCHAR | Postal code — indexed |
| `L_Class` | VARCHAR | Property class: Residential, CommercialSale, Land, etc. |
| `L_Type_` | VARCHAR | Subtype: SingleFamilyResidence, Condominium, etc. — indexed |
| `L_Keyword2` | INT | Bedrooms total |
| `LM_Dec_3` | DECIMAL(4,1) | Bathrooms total (supports half-baths, e.g. 2.5) |
| `L_SystemPrice` | INT | Current list price (search/display price) |
| `LM_Int2_3` | INT | Approximate finished square footage |
| `L_Keyword1` | VARCHAR | Lot size (string, often sq ft or acres) |
| `LMD_MP_Latitude` | DECIMAL(18,15) | Geo latitude — high precision |
| `LMD_MP_Longitude` | DECIMAL(19,15) | Geo longitude — high precision |
| `L_Status` | VARCHAR | Listing status: Active, Pending, Withdrawn, etc. |
| `L_Remarks` | MEDIUMTEXT | Full listing description — FULLTEXT indexed (`ft_remarks`) |
| `L_Photos` | LONGTEXT | JSON array of Cotality/Trestle photo URLs |
| `LA1_UserFirstName` / `LA1_UserLastName` | VARCHAR | Listing agent name |
| `ListAgentEmail` | VARCHAR | Listing agent email address |
| `ListAgentDirectPhone` | VARCHAR | Listing agent direct phone |
| `LO1_OrganizationName` | VARCHAR | Listing office / brokerage name |
| `ListingContractDate` | DATE | Date listing agreement was signed |
| `YearBuilt` | INT | Year property was constructed |
| `SubdivisionName` | VARCHAR | Subdivision or community name |
| `AssociationFee` | INT | Monthly HOA fee in dollars |
| `AssociationAmenities` | TEXT | HOA amenities: Golf, Pool, Tennis, etc. |
| `DaysOnMarket` | INT | Days on market at time of data pull |
| `PoolPrivateYN` | VARCHAR | Private pool present (True/False) |
| `FireplaceYN` | VARCHAR | Fireplace present (True/False) |
| `ViewYN` | VARCHAR | Has a notable view (True/False) |
| `View` | VARCHAR | View description: Mountains, Ocean, GolfCourse, etc. |
| `LotSizeAcres` | DECIMAL(10,4) | Lot size in acres |
| `LotSizeSquareFeet` | DECIMAL(14,2) | Lot size in square feet |
| `PreviousListPrice` | DECIMAL(12,0) | Prior list price — enables price reduction analysis |
| `StandardStatus` | VARCHAR | RESO standard status: Active, Pending, Closed |
| `CountyOrParish` | VARCHAR | County name (e.g., Riverside, Los Angeles) |
| `ParcelNumber` | VARCHAR | Assessor parcel number (APN) |
| `Cooling` / `Heating` | VARCHAR | HVAC system type |
| `ArchitecturalStyle` | VARCHAR | Modern, Ranch, Mediterranean, etc. |
| `PhotoCount` | INT | Number of listing photos available |
| `ModificationTimestamp` | DATETIME | Last modification timestamp for incremental sync |

## california_sold — Sold Transactions

The historical comps and market analytics table (~439K sold, leased, and
closed transactions, 2021–2025, 46 fields).

| Column | Type | Description |
|---|---|---|
| `ListingKey` | BIGINT | Unique listing identifier — joins to `rets_property.L_ListingID` |
| `ClosePrice` | DOUBLE | Final sale/close price |
| `CloseDate` | VARCHAR | Date the transaction closed (YYYY-MM-DD) |
| `OriginalListPrice` | DOUBLE | Original asking price when first listed |
| `ListPrice` | DOUBLE | List price at time of contract |
| `DaysOnMarket` | BIGINT | Days from listing to contract |
| `PropertyType` | VARCHAR | Residential, Land, ResidentialLease, CommercialSale, etc. |
| `PropertySubType` | VARCHAR | SingleFamilyResidence, Condominium, Duplex, etc. |
| `LivingArea` | DOUBLE | Finished living area in square feet |
| `LotSizeAcres` / `LotSizeSquareFeet` | DOUBLE | Lot size |
| `BedroomsTotal` | DOUBLE | Number of bedrooms |
| `BathroomsTotalInteger` | DOUBLE | Number of bathrooms |
| `YearBuilt` | DOUBLE | Year property was built |
| `City` / `PostalCode` | VARCHAR | Location |
| `Latitude` / `Longitude` | DOUBLE | Geographic coordinates |
| `UnparsedAddress` | VARCHAR | Full street address |
| `ListAgentFirstName` / `ListAgentLastName` / `ListAgentFullName` | VARCHAR | List agent |
| `BuyerAgentFirstName` / `BuyerAgentLastName` | VARCHAR | Buyer agent |
| `ListOfficeName` / `BuyerOfficeName` | VARCHAR | Brokerages |
| `PoolPrivateYN` / `ViewYN` / `FireplaceYN` | VARCHAR | Amenity flags (True/False/empty) |
| `NewConstructionYN` | VARCHAR | New construction (True/False) |
| `GarageSpaces` | DOUBLE | Number of garage spaces |
| `AssociationFee` | DOUBLE | Monthly HOA fee |
| `SubdivisionName` | VARCHAR | Subdivision / community name |
| `HighSchoolDistrict` | VARCHAR | School district name |
| `ListingContractDate` | VARCHAR | Date listing was entered (YYYY-MM-DD) |
| `PurchaseContractDate` | VARCHAR | Date offer was accepted |

## Key Join Pattern

To correlate active listings with sold comps:

```sql
JOIN rets_property r ON CAST(r.L_ListingID AS UNSIGNED) = cs.ListingKey
```

Or match on city + postal code for market-level analysis when a direct
listing-to-comp join isn't available.
