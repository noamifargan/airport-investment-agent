"""Tiny client for Socrata Open Data (SODA) APIs — used by data.bts.gov and data.transportation.gov."""

from __future__ import annotations

from airport_agent.data.store import get_with_retry

PAGE = 50_000


def soql(domain: str, dataset: str, params: dict[str, str], *, max_rows: int = 2_000_000) -> tuple[list[dict], str]:
    """Run a SoQL query, paging through results. Returns (rows, first-page URL for provenance)."""
    rows: list[dict] = []
    first_url = ""
    offset = 0
    while True:
        page = {**params, "$limit": str(PAGE), "$offset": str(offset)}
        resp = get_with_retry(f"https://{domain}/resource/{dataset}.json", params=page)
        first_url = first_url or str(resp.url)
        batch = resp.json()
        rows.extend(batch)
        if len(batch) < PAGE or len(rows) >= max_rows:
            return rows, first_url
        offset += PAGE
