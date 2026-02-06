from dataclasses import dataclass
from typing import Optional


@dataclass
class Auction:
    auction_id: str
    facility_name: str
    address: str
    city: str
    state: str
    postal_code: str
    phone: str
    auction_date: str
    auction_time: str
    units: str
    details_url: str


@dataclass
class Tenant:
    unit: str
    name: str
    description: str


@dataclass
class Hit:
    auction_id: str
    tenant_name: str
    facility_name: str
    address: str
    city: str
    state: str
    postal_code: str
    auction_date: str
    auction_time: str
    details_url: str
    is_known: bool
    known_for: str
    scope: str  # "local", "regional", "national", "international", or "unknown"
    confidence: float
    reasoning: str
