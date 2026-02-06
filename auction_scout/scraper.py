import os
import re
from urllib.parse import urljoin
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from .models import Auction, Tenant

# Full mapping of US state abbreviations to URL-friendly names
_STATE_NAME_MAP = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas",
    "CA": "california", "CO": "colorado", "CT": "connecticut", "DE": "delaware",
    "FL": "florida", "GA": "georgia", "HI": "hawaii", "ID": "idaho",
    "IL": "illinois", "IN": "indiana", "IA": "iowa", "KS": "kansas",
    "KY": "kentucky", "LA": "louisiana", "ME": "maine", "MD": "maryland",
    "MA": "massachusetts", "MI": "michigan", "MN": "minnesota", "MS": "mississippi",
    "MO": "missouri", "MT": "montana", "NE": "nebraska", "NV": "nevada",
    "NH": "new-hampshire", "NJ": "new-jersey", "NM": "new-mexico", "NY": "new-york",
    "NC": "north-carolina", "ND": "north-dakota", "OH": "ohio", "OK": "oklahoma",
    "OR": "oregon", "PA": "pennsylvania", "RI": "rhode-island", "SC": "south-carolina",
    "SD": "south-dakota", "TN": "tennessee", "TX": "texas", "UT": "utah",
    "VT": "vermont", "VA": "virginia", "WA": "washington", "WV": "west-virginia",
    "WI": "wisconsin", "WY": "wyoming", "DC": "district-of-columbia",
}

BASE_URL = "https://auctions-storage.com"


def build_state_urls(states: List[str]) -> Dict[str, str]:
    """Generate STATE_URLS dict from a list of state abbreviations."""
    urls = {}
    for code in states:
        code = code.strip().upper()
        slug = _STATE_NAME_MAP.get(code)
        if slug:
            urls[code] = f"{BASE_URL}/storage-auction/{slug}/default.aspx"
    return urls


def _get_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (AuctionScout/1.0; +https://auctions-storage.com/)"
    }
    full_url = urljoin(BASE_URL, url)
    resp = requests.get(full_url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.text


def _extract_auction_id(url: str) -> Optional[str]:
    match = re.search(r"auctionID=(\d+)", url, re.IGNORECASE)
    return match.group(1) if match else None


def _parse_city_state_zip(text: str) -> Dict[str, str]:
    text = text.strip()
    match = re.match(r"(.+?),\s*([A-Z]{2})\s*(\d{5})?", text)
    if not match:
        return {"city": "", "state": "", "postal": ""}
    return {"city": match.group(1).strip(), "state": match.group(2), "postal": match.group(3) or ""}


def _row_to_auction(row) -> Optional[Auction]:
    cells = row.find_all("td")
    if len(cells) < 7:
        return None

    facility_link = None
    for a in row.find_all("a"):
        if "auctionID=" not in (a.get("href") or ""):
            facility_link = a
            break

    facility_name = facility_link.get_text(strip=True) if facility_link else ""
    address = cells[1].get_text(" ", strip=True)
    city_state_zip = _parse_city_state_zip(cells[2].get_text(" ", strip=True))
    phone = cells[3].get_text(" ", strip=True)
    auction_date = cells[4].get_text(" ", strip=True)
    auction_time = cells[5].get_text(" ", strip=True)
    units = cells[6].get_text(" ", strip=True)

    details_link = row.find("a", string=re.compile(r"Auction Details", re.I))
    details_url = details_link.get("href") if details_link else ""
    if details_url:
        details_url = urljoin(BASE_URL, details_url)
    auction_id = _extract_auction_id(details_url or "") or ""

    if not city_state_zip["state"] or not auction_id:
        return None

    return Auction(
        auction_id=auction_id,
        facility_name=facility_name,
        address=address,
        city=city_state_zip["city"],
        state=city_state_zip["state"],
        postal_code=city_state_zip["postal"],
        phone=phone,
        auction_date=auction_date,
        auction_time=auction_time,
        units=units,
        details_url=details_url,
    )


def _grid_to_auction(grid) -> Optional[Auction]:
    facility = grid.select_one(".auctions-col-facility")
    if not facility:
        return None

    lines = [s.strip() for s in facility.stripped_strings if s.strip()]
    facility_name = lines[0] if lines else ""

    address = ""
    city_state_zip_line = ""
    phone = ""
    for line in lines[1:]:
        if re.search(r"\b[A-Z]{2}\b", line) and "," in line:
            city_state_zip_line = line
        elif re.search(r"\d{7,}", line):
            phone = line
        elif not address:
            address = line

    city_state_zip = _parse_city_state_zip(city_state_zip_line)

    auction_date = ""
    auction_time = ""
    units = ""
    date_el = grid.select_one(".auctions-col-date2")
    time_el = grid.select_one(".auctions-col-time2")
    units_el = grid.select_one(".auctions-col-units2")
    if date_el:
        auction_date = date_el.get_text(" ", strip=True)
    if time_el:
        auction_time = time_el.get_text(" ", strip=True)
    if units_el:
        units = units_el.get_text(" ", strip=True)

        details_link = grid.select_one(".auctions-col-details a[href*='auctionID=']")
    if not details_link:
        details_link = grid.find("a", href=re.compile(r"auctionID=", re.I))
    details_url = details_link.get("href") if details_link else ""
    if details_url:
        details_url = urljoin(BASE_URL, details_url)
    auction_id = _extract_auction_id(details_url or "") or ""

    if not city_state_zip["state"] or not auction_id:
        return None

    return Auction(
        auction_id=auction_id,
        facility_name=facility_name,
        address=address,
        city=city_state_zip["city"],
        state=city_state_zip["state"],
        postal_code=city_state_zip["postal"],
        phone=phone,
        auction_date=auction_date,
        auction_time=auction_time,
        units=units,
        details_url=details_url,
    )


def fetch_state_auctions(state: str, state_urls: Dict[str, str]) -> List[Auction]:
    url = state_urls[state]
    html = _get_html(url)
    soup = BeautifulSoup(html, "html.parser")
    auctions: Dict[str, Auction] = {}

    for grid in soup.select("div.auctions-result-grid"):
        auction = _grid_to_auction(grid)
        if auction:
            auctions[auction.auction_id] = auction

    for a in soup.select("a[href*='auctionID=']"):
        row = a.find_parent("tr")
        if row:
            auction = _row_to_auction(row)
            if auction:
                auctions[auction.auction_id] = auction

    if auctions:
        return list(auctions.values())

    for li in soup.find_all("li"):
        link = li.find("a", href=re.compile(r"auctionID=", re.I))
        if not link:
            continue
        auction_id = _extract_auction_id(link.get("href") or "") or ""
        if not auction_id:
            continue
        text = li.get_text(" ", strip=True)
        match = re.search(r"-\s*([^,]+),\s*([A-Z]{2})", text)
        if not match:
            continue
        state_code = match.group(2)
        details_url = urljoin(BASE_URL, link.get("href"))
        auctions[auction_id] = Auction(
            auction_id=auction_id,
            facility_name=link.get_text(strip=True),
            address="",
            city=match.group(1).strip(),
            state=state_code,
            postal_code="",
            phone="",
            auction_date=text.split(":")[0].replace("•", "").strip(),
            auction_time="",
            units="",
            details_url=details_url,
        )

    return list(auctions.values())


def fetch_tenants(details_url: str) -> List[Tenant]:
    html = _get_html(details_url)
    soup = BeautifulSoup(html, "html.parser")

    tables = soup.find_all("table")
    target_table = None
    for table in tables:
        headers = " ".join([th.get_text(" ", strip=True) for th in table.find_all("th")])
        if "Tenant Name" in headers:
            target_table = table
            break

    if not target_table:
        tenants: List[Tenant] = []
        for row in soup.select("div.auctions-result-grid"):
            unit = row.select_one(".auctions-col-unit2")
            name = row.select_one(".auctions-col-tenant2")
            desc = row.select_one(".auctions-col-goods")
            unit_text = unit.get_text(" ", strip=True) if unit else ""
            name_text = name.get_text(" ", strip=True) if name else ""
            desc_text = desc.get_text(" ", strip=True) if desc else ""
            if name_text:
                tenants.append(Tenant(unit=unit_text, name=name_text, description=desc_text))
        return tenants

    tenants: List[Tenant] = []
    rows = target_table.find_all("tr")
    for row in rows[1:]:
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"]) if c.get_text(strip=True)]
        if len(cells) < 2:
            continue
        unit = cells[0]
        name = cells[1]
        description = cells[2] if len(cells) > 2 else ""
        tenants.append(Tenant(unit=unit, name=name, description=description))

    return tenants
