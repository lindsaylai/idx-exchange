# property-search

Parse a free-text real estate query into structured filters, then (Week 3+) query the MLS database.

## When to use

Use this skill when the user asks to find, search, or show properties — e.g.:
- "Show me 3-bedroom condos in Irvine under $1.5M"
- "Find homes in Pasadena with a pool"
- "Any land for sale in Malibu?"

## Week 2: Query Parser

Run `parse_query.py` to convert the user's message into a structured filter object.

```bash
cd /Users/lindsaylai/projects/idx-exchange
source venv/bin/activate
python -c "
from skills.property_search.parse_query import parse_property_query
import json
result = parse_property_query('<USER_QUERY>')
print(json.dumps(result, indent=2))
"
```

### Output fields → rets_property columns

| Field      | DB Column        | Example        |
|------------|------------------|----------------|
| city       | L_City           | "Irvine"       |
| maxPrice   | L_SystemPrice    | 1500000        |
| beds       | L_Keyword2       | 3              |
| baths      | LM_Dec_3         | 2.5            |
| sqft       | LM_Int2_3        | 1800           |
| type       | L_Type_          | "Condominium"  |
| pool       | PoolPrivateYN    | "True"         |
| hasView    | ViewYN           | "True"         |
| maxHOA     | AssociationFee   | 300            |

All values are `null` when not mentioned in the query.

## Week 3+: Database query

Filters from the parser will feed into `searchActiveListings()` against `rets_property`.
Key join for comps: `CAST(rets_property.L_ListingID AS UNSIGNED) = california_sold.ListingKey`
