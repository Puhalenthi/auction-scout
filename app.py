import argparse
import os
import re
import time
from datetime import datetime
from typing import Dict, List

from dotenv import load_dotenv

from auction_scout.gpt import GPTNameChecker
from auction_scout.models import Hit
from auction_scout.scraper import build_state_urls, fetch_state_auctions, fetch_tenants
from auction_scout.storage import append_csv, append_hits_json, load_json, save_json


DATA_DIR = "data"
OUTPUT_DIR = "output"
CACHE_FILE = os.path.join(DATA_DIR, "gpt_cache.json")
SEEN_FILE = os.path.join(DATA_DIR, "seen_auction_ids.json")
HITS_FILE = os.path.join(OUTPUT_DIR, "hits.json")
HITS_CSV = os.path.join(OUTPUT_DIR, "hits.csv")
BATCH_SIZE = 10
ENV_STATES = "AUCTION_STATES"


# ── colour helpers ──────────────────────────────────────────────────────────

def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"

def _header(text: str) -> str:
    """Bold cyan – section headers"""
    return _c(text, "1;96")

def _info(text: str) -> str:
    """Cyan – general info"""
    return _c(text, "36")

def _success(text: str) -> str:
    """Green – hits / good news"""
    return _c(text, "32")

def _warn(text: str) -> str:
    """Yellow – skipped / cached"""
    return _c(text, "33")

def _error(text: str) -> str:
    """Red – errors"""
    return _c(text, "31")

def _gpt(text: str) -> str:
    """Magenta – GPT activity"""
    return _c(text, "35")

def _batch(text: str) -> str:
    """Bold magenta – GPT batch sends"""
    return _c(text, "1;35")

def _auction(text: str) -> str:
    """Bold blue – auction progress [X/X]"""
    return _c(text, "1;34")

def _not_known(text: str) -> str:
    """Red – person not known"""
    return _c(text, "31")

def _dim(text: str) -> str:
    """Grey – low-importance detail"""
    return _c(text, "90")

def _ts() -> str:
    """Timestamp prefix"""
    return _dim(datetime.now().strftime("[%H:%M:%S]"))


# ── helpers ─────────────────────────────────────────────────────────────────

def _looks_like_person(name: str) -> bool:
    name = name.strip()
    if len(name) < 4:
        return False
    if any(x in name.lower() for x in ["llc", "inc", "storage", "estate", "trust", "company"]):
        return False
    if re.search(r"\d", name):
        return False
    return len(name.split()) >= 2


def _hit_to_dict(hit: Hit) -> Dict[str, str]:
    return {
        "auction_id": hit.auction_id,
        "tenant_name": hit.tenant_name,
        "facility_name": hit.facility_name,
        "address": hit.address,
        "city": hit.city,
        "state": hit.state,
        "postal_code": hit.postal_code,
        "auction_date": hit.auction_date,
        "auction_time": hit.auction_time,
        "details_url": hit.details_url,
        "is_known": str(hit.is_known),
        "known_for": hit.known_for,
        "scope": hit.scope,
        "confidence": f"{hit.confidence:.2f}",
        "reasoning": hit.reasoning,
    }


# ── main scan logic ────────────────────────────────────────────────────────

def run_once(states: List[str]) -> List[Hit]:
    load_dotenv()
    checker = GPTNameChecker()

    # Build state URLs dynamically
    state_urls = build_state_urls(states)
    if not state_urls:
        print(_error(f"{_ts()} No valid state URLs could be built for: {states}"))
        return []

    cache: dict = load_json(CACHE_FILE, {})
    seen: set = set(load_json(SEEN_FILE, []))
    all_hits: List[Hit] = []

    # Stats
    stats = {"auctions_scraped": 0, "people_scraped": 0, "gpt_batches": 0,
             "gpt_people": 0, "hits_found": 0, "cached_skipped": 0,
             "auctions_skipped": 0, "non_person_skipped": 0}

    print(_header(f"\n{'═' * 60}"))
    print(_header(f"  AUCTION SCOUT — Scanning {', '.join(states)}"))
    print(_header(f"{'═' * 60}\n"))

    # Phase 1: Scrape all auctions per state
    print(_info(f"{_ts()} Phase 1: Fetching auction listings..."))
    all_auctions = []
    for state in states:
        if state not in state_urls:
            print(_warn(f"{_ts()}   Skipping {state} — no URL mapping"))
            continue
        print(_info(f"{_ts()}   Fetching {state} auctions..."), flush=True)
        try:
            auctions = fetch_state_auctions(state, state_urls)
            new_auctions = [a for a in auctions if a.auction_id not in seen]
            skipped = len(auctions) - len(new_auctions)
            stats["auctions_skipped"] += skipped
            all_auctions.extend(new_auctions)
            print(_info(f"{_ts()}   {state}: {len(new_auctions)} new auctions "
                        f"({skipped} previously seen)"), flush=True)
        except Exception as exc:
            print(_error(f"{_ts()}   Error fetching {state}: {exc}"), flush=True)

    total_auctions = len(all_auctions)
    print(_info(f"{_ts()}   Total new auctions to process: {total_auctions}\n"))

    if total_auctions == 0:
        print(_warn(f"{_ts()} No new auctions to process. Done."))
        return []

    # Phase 2: Scrape tenants & process in batches of BATCH_SIZE people
    print(_info(f"{_ts()} Phase 2: Scraping tenants & checking with GPT (batch size={BATCH_SIZE})...\n"))

    pending_items: List[dict] = []       # items to send to GPT
    pending_refs: List[tuple] = []       # (tenant, cache_key, auction)

    def flush_pending() -> None:
        """Send accumulated people to GPT and process results."""
        if not pending_items:
            return
        stats["gpt_batches"] += 1
        stats["gpt_people"] += len(pending_items)
        names_preview = ", ".join(item["name"] for item in pending_items[:3])
        if len(pending_items) > 3:
            names_preview += f" … +{len(pending_items) - 3} more"
        print(_batch(f"{_ts()}   ► GPT batch #{stats['gpt_batches']}: "
                      f"sending {len(pending_items)} people [{names_preview}]"), flush=True)

        try:
            results = checker.check_names_batch(pending_items)
        except Exception as exc:
            print(_error(f"{_ts()}     GPT error: {exc}"), flush=True)
            pending_items.clear()
            pending_refs.clear()
            return

        batch_hits: List[Dict[str, str]] = []
        for result, (tenant, key, auction) in zip(results, pending_refs):
            # Cache the result immediately
            cache[key] = result
            save_json(CACHE_FILE, cache)

            is_known = result.get("is_known", False)
            if is_known:
                hit = Hit(
                    auction_id=auction.auction_id,
                    tenant_name=tenant.name,
                    facility_name=auction.facility_name,
                    address=auction.address,
                    city=auction.city,
                    state=auction.state,
                    postal_code=auction.postal_code,
                    auction_date=auction.auction_date,
                    auction_time=auction.auction_time,
                    details_url=auction.details_url,
                    is_known=True,
                    known_for=result.get("known_for", ""),
                    scope=result.get("scope", "unknown"),
                    confidence=result.get("confidence", 0.0),
                    reasoning=result.get("reasoning", ""),
                )
                all_hits.append(hit)
                stats["hits_found"] += 1
                batch_hits.append(_hit_to_dict(hit))
                print(_success(f"{_ts()}     ★ HIT: {tenant.name} — "
                               f"{result.get('known_for', '?')} "
                               f"(scope: {result.get('scope', '?')}, "
                               f"confidence: {result.get('confidence', 0):.0%})"), flush=True)
            else:
                print(_not_known(f"{_ts()}     ✗ {tenant.name} — not known"), flush=True)

        # Save hits incrementally
        if batch_hits:
            append_hits_json(HITS_FILE, batch_hits)
            append_csv(HITS_CSV, batch_hits)
            print(_success(f"{_ts()}     Saved {len(batch_hits)} hit(s) to hits.json"), flush=True)

        pending_items.clear()
        pending_refs.clear()

    for idx, auction in enumerate(all_auctions, 1):
        print(_auction(f"{_ts()}  [{idx}/{total_auctions}] Auction {auction.auction_id} — "
                      f"{auction.facility_name}, {auction.city}, {auction.state}"), flush=True)
        print(_dim(f"{_ts()}    URL: {auction.details_url}"), flush=True)

        try:
            tenants = fetch_tenants(auction.details_url)
        except Exception as exc:
            print(_error(f"{_ts()}    Error fetching tenants: {exc}"), flush=True)
            seen.add(auction.auction_id)
            save_json(SEEN_FILE, sorted(seen))
            continue

        print(_info(f"{_ts()}    Found {len(tenants)} tenant(s)"), flush=True)
        stats["auctions_scraped"] += 1

        for tenant in tenants:
            if not _looks_like_person(tenant.name):
                stats["non_person_skipped"] += 1
                print(_dim(f"{_ts()}      Skip (not a person): {tenant.name}"), flush=True)
                continue

            stats["people_scraped"] += 1
            key = f"{tenant.name}|{auction.city}|{auction.state}"

            if key in cache:
                stats["cached_skipped"] += 1
                cached = cache[key]
                is_known = False
                if isinstance(cached, dict):
                    is_known = cached.get("is_known", False)
                print(_warn(f"{_ts()}      Cached: {tenant.name} → "
                            f"{'KNOWN' if is_known else 'not known'}"), flush=True)
                # Still record the hit if it was known
                if is_known:
                    hit = Hit(
                        auction_id=auction.auction_id,
                        tenant_name=tenant.name,
                        facility_name=auction.facility_name,
                        address=auction.address,
                        city=auction.city,
                        state=auction.state,
                        postal_code=auction.postal_code,
                        auction_date=auction.auction_date,
                        auction_time=auction.auction_time,
                        details_url=auction.details_url,
                        is_known=True,
                        known_for=cached.get("known_for", ""),
                        scope=cached.get("scope", "unknown"),
                        confidence=cached.get("confidence", 0.0),
                        reasoning=cached.get("reasoning", ""),
                    )
                    all_hits.append(hit)
                    hit_dict = _hit_to_dict(hit)
                    append_hits_json(HITS_FILE, [hit_dict])
                    append_csv(HITS_CSV, [hit_dict])
                    stats["hits_found"] += 1
                continue

            pending_items.append({
                "index": len(pending_items),
                "name": tenant.name,
                "city": auction.city,
                "state": auction.state,
                "address": auction.address,
            })
            pending_refs.append((tenant, key, auction))

            if len(pending_items) >= BATCH_SIZE:
                flush_pending()

        # Mark auction as seen immediately and persist
        seen.add(auction.auction_id)
        save_json(SEEN_FILE, sorted(seen))

    # Flush any remaining items
    flush_pending()

    # Final summary
    print(_header(f"\n{'═' * 60}"))
    print(_header("  SCAN COMPLETE — SUMMARY"))
    print(_header(f"{'═' * 60}"))
    print(_auction(f"  Auctions scraped:     {stats['auctions_scraped']}"))
    print(_warn(f"  Auctions skipped:     {stats['auctions_skipped']} (previously seen)"))
    print(_info(f"  People scraped:       {stats['people_scraped']}"))
    print(_dim(f"  Non-person skipped:   {stats['non_person_skipped']}"))
    print(_warn(f"  Cached (skipped GPT): {stats['cached_skipped']}"))
    print(_batch(f"  GPT batches sent:     {stats['gpt_batches']}"))
    print(_batch(f"  GPT people checked:   {stats['gpt_people']}"))
    print(_success(f"  Hits found:           {stats['hits_found']}"))
    print(_header(f"{'═' * 60}\n"))

    return all_hits


def main() -> None:
    parser = argparse.ArgumentParser(description="Auction Scout - community-known person tracker")
    parser.add_argument("--states", nargs="*", help="States to scan (overrides .env)")
    parser.add_argument("--watch", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=3600, help="Seconds between scans")
    args = parser.parse_args()

    load_dotenv()

    # Determine states: CLI args > .env > default
    if args.states:
        states = [s.strip().upper() for s in args.states if s.strip()]
    else:
        env_states = os.environ.get(ENV_STATES, "").strip()
        if env_states:
            states = [s.strip().upper() for s in env_states.split(",") if s.strip()]
        else:
            print(_error("No states configured. Set AUCTION_STATES in .env (e.g. AUCTION_STATES=NJ,NY,CT)"))
            return

    # Validate we can build URLs for these states
    state_urls = build_state_urls(states)
    valid_states = list(state_urls.keys())
    if not valid_states:
        print(_error(f"No valid state abbreviations found in: {states}"))
        return

    invalid = set(states) - set(valid_states)
    if invalid:
        print(_warn(f"Ignoring unknown state codes: {', '.join(sorted(invalid))}"))

    states = valid_states
    print(_header(f"Auction Scout starting for: {', '.join(states)}"))

    if args.watch:
        while True:
            hits = run_once(states)
            if hits:
                for hit in hits:
                    print(_success(f"  ★ {hit.tenant_name} — {hit.known_for} → {hit.details_url}"))
            else:
                print(_warn("  No hits found this scan."))
            print(_info(f"  Sleeping {args.interval}s until next scan…\n"))
            time.sleep(args.interval)
    else:
        hits = run_once(states)
        if hits:
            print(_success(f"\nAll hits written to {HITS_FILE}"))
        else:
            print(_warn("\nNo hits found."))


if __name__ == "__main__":
    main()
