"""FAA NAS Status — live airport delay programs (https://nasstatus.faa.gov/api/airport-status-information).

Real-time XML feed of Ground Delay Programs, Ground Stops, general arrival/departure delays
and airport closure NOTAMs. Refreshed every couple of minutes; no key.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from airport_agent.data.store import Provenance, fetch_bytes

URL = "https://nasstatus.faa.gov/api/airport-status-information"
LABEL = "FAA NAS Status (live)"


def _text(node: ET.Element, tag: str) -> str:
    found = node.find(tag)
    return (found.text or "").strip() if found is not None else ""


def parse(xml: bytes) -> tuple[str, list[dict]]:
    root = ET.fromstring(xml)
    updated = _text(root, "Update_Time")
    events: list[dict] = []
    for delay_type in root.findall("Delay_type"):
        for gd in delay_type.iter("Ground_Delay"):
            events.append({"airport": _text(gd, "ARPT"), "type": "Ground Delay Program", "reason": _text(gd, "Reason"),
                           "detail": f"avg {_text(gd, 'Avg')}, max {_text(gd, 'Max')}"})
        for gs in delay_type.iter("Program"):
            events.append({"airport": _text(gs, "ARPT"), "type": "Ground Stop", "reason": _text(gs, "Reason"),
                           "detail": f"until {_text(gs, 'End_Time')}"})
        for d in delay_type.iter("Delay"):
            ad = d.find("Arrival_Departure")
            direction = ad.get("Type", "") if ad is not None else ""
            detail = f"{direction.lower()} delays {_text(ad, 'Min')}–{_text(ad, 'Max')}, {_text(ad, 'Trend').lower()}" if ad is not None else ""
            events.append({"airport": _text(d, "ARPT"), "type": "Delay", "reason": _text(d, "Reason"), "detail": detail})
        for ap in delay_type.iter("Airport"):
            events.append({"airport": _text(ap, "ARPT"), "type": "Closure/restriction NOTAM",
                           "reason": _text(ap, "Reason")[:90], "detail": f"{_text(ap, 'Start')} → {_text(ap, 'Reopen')}"})
    return updated, events


def current_events() -> tuple[list[dict], str, Provenance]:
    """All airport events active right now, the feed's own update time, and provenance."""
    xml, prov = fetch_bytes("faa_nas", "airport_status", URL, label=LABEL, ttl=120, ext="xml", coverage="real-time")
    updated, events = parse(xml)
    return events, updated, prov


def events_for(iata: str) -> tuple[list[dict], str, Provenance]:
    events, updated, prov = current_events()
    return [e for e in events if e["airport"] == iata.upper()], updated, prov
