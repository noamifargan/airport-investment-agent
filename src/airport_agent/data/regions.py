"""US states and the regional groupings an analyst is likely to ask about."""

from __future__ import annotations

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "PR": "Puerto Rico", "VI": "U.S. Virgin Islands", "GU": "Guam",
}

_DIVISIONS = {
    "New England": ["CT", "ME", "MA", "NH", "RI", "VT"],
    "Mid-Atlantic": ["NJ", "NY", "PA"],
    "East North Central": ["IL", "IN", "MI", "OH", "WI"],
    "West North Central": ["IA", "KS", "MN", "MO", "NE", "ND", "SD"],
    "South Atlantic": ["DE", "DC", "FL", "GA", "MD", "NC", "SC", "VA", "WV"],
    "East South Central": ["AL", "KY", "MS", "TN"],
    "West South Central": ["AR", "LA", "OK", "TX"],
    "Mountain": ["AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY"],
    "Pacific": ["AK", "CA", "HI", "OR", "WA"],
}

_lower48 = [s for s in STATES if s not in {"AK", "HI", "PR", "VI", "GU"}]

# Region name -> member states. Census regions/divisions plus common informal groupings.
REGIONS: dict[str, list[str]] = {
    **_DIVISIONS,
    "Northeast": _DIVISIONS["New England"] + _DIVISIONS["Mid-Atlantic"],
    "Midwest": _DIVISIONS["East North Central"] + _DIVISIONS["West North Central"],
    "South": _DIVISIONS["South Atlantic"] + _DIVISIONS["East South Central"] + _DIVISIONS["West South Central"],
    "West": _DIVISIONS["Mountain"] + _DIVISIONS["Pacific"],
    "West Coast": ["CA", "OR", "WA"],
    "East Coast": ["ME", "NH", "MA", "RI", "CT", "NY", "NJ", "DE", "MD", "DC", "VA", "NC", "SC", "GA", "FL"],
    "Pacific Northwest": ["WA", "OR", "ID"],
    "Southwest": ["AZ", "NM", "NV", "UT"],
    "Southeast": ["AL", "FL", "GA", "MS", "NC", "SC", "TN"],
    "Great Lakes": ["IL", "IN", "MI", "MN", "NY", "OH", "PA", "WI"],
    "Rocky Mountains": ["CO", "ID", "MT", "UT", "WY"],
    "Gulf Coast": ["TX", "LA", "MS", "AL", "FL"],
    "Lower 48": _lower48,
    "United States": list(STATES),
}

# Extra phrasings that map onto a region above.
REGION_ALIASES = {
    "new england": "New England",
    "mid atlantic": "Mid-Atlantic",
    "mid-atlantic": "Mid-Atlantic",
    "northeast": "Northeast",
    "north east": "Northeast",
    "midwest": "Midwest",
    "mid west": "Midwest",
    "the south": "South",
    "southeast": "Southeast",
    "south east": "Southeast",
    "southwest": "Southwest",
    "south west": "Southwest",
    "west coast": "West Coast",
    "east coast": "East Coast",
    "pacific northwest": "Pacific Northwest",
    "great lakes": "Great Lakes",
    "rocky mountains": "Rocky Mountains",
    "mountain west": "Mountain",
    "gulf coast": "Gulf Coast",
    "lower 48": "Lower 48",
    "contiguous us": "Lower 48",
    "continental us": "Lower 48",
    "nationwide": "United States",
    "national": "United States",
    "the us": "United States",
    "the u.s.": "United States",
    "united states": "United States",
    "the country": "United States",
    "usa": "United States",
}
