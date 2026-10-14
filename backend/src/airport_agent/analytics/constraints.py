"""Hand-curated structural constraints that public APIs don't expose.

Static context, not live data — each entry names its source so analysts can verify it.
Kept deliberately short: only well-documented, decision-relevant facts.
"""

KNOWN_CONSTRAINTS: dict[str, list[dict]] = {
    "SNA": [
        {"fact": "Commercial passengers and departures are capped by a court-approved Settlement Agreement "
                 "with the City of Newport Beach (roughly 11.8M annual passengers in the current phase).",
         "source": "https://www.ocair.com (Access Plan / Settlement Agreement)"},
        {"fact": "Noise curfew: no commercial departures before 7:00 (8:00 Sunday) or after 22:00.",
         "source": "https://www.ocair.com (General Aviation Noise Ordinance)"},
        {"fact": "Only one air-carrier runway (5,700 ft), which limits aircraft size and range.",
         "source": "OurAirports runway data"},
    ],
    "SFO": [
        {"fact": "Both parallel runway pairs are only ~750 ft apart; in low ceilings (frequent marine-layer fog) "
                 "side-by-side approaches stop and arrival capacity roughly halves, triggering Ground Delay Programs.",
         "source": "FAA SFO capacity profile; runway geometry from OurAirports"},
        {"fact": "Expanding runways into San Francisco Bay has been studied and rejected, so airside capacity is "
                 "effectively fixed.",
         "source": "SFO Runway Reconfiguration Project (2008–2009, discontinued)"},
    ],
    "LGA": [
        {"fact": "Slot-controlled (IATA Level 3) and subject to a 1,500-mile perimeter rule.",
         "source": "FAA slot administration; Port Authority perimeter rule"},
    ],
    "JFK": [{"fact": "Slot-controlled (IATA Level 3).", "source": "FAA slot administration"}],
    "DCA": [
        {"fact": "Slot-controlled with a federal 1,250-mile perimeter rule (limited exemptions).",
         "source": "49 U.S.C. 49109; FAA High Density Rule"},
    ],
    "ANC": [
        {"fact": "One of the world's busiest cargo airports: a refuelling / transfer point for freighters between "
                 "Asia and North America, so cargo dominates its long-haul traffic.",
         "source": "Airport traffic reports; BTS T-100 freight volumes"},
    ],
}
