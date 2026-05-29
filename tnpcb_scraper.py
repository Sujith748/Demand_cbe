"""
TNPCB Scraper — Kongu Industrial Corridor
==========================================
Saves to: results/YYYY-MM-DD_HH-MM_tnpcb/tnpcb_signals.csv
Updates:  results/latest.json

Usage:
    python3 tnpcb_scraper.py
"""

import requests
from bs4 import BeautifulSoup
import csv
import time
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

# ── Date range ────────────────────────────────────────────────────
TO_DATE   = datetime.today().strftime("%Y-%m-%d")
FROM_DATE = (datetime.today() - timedelta(days=180)).strftime("%Y-%m-%d")

# ── Regions ───────────────────────────────────────────────────────
KNOWN_REGIONS = {
    "DEE CBE NORTH": 100498,
}
TARGET_REGIONS = [
    "DEE CBE SOUTH",
    "DEE TIRUPPUR NORTH",
    "DEE TIRUPPUR SOUTH",
    "DEE ERODE",
]
APPLICATION_TYPES = ["CTE", "CTO"]

FIELDNAMES = [
    "company_name", "industry_address", "application_no",
    "application_date", "application_type", "status",
    "district", "region", "signal_type", "source", "scraped_date",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://ocmms.tn.gov.in/OCMMS/allReports/searchDashboard",
}
BASE = "https://ocmms.tn.gov.in"


# ── Output folder setup ───────────────────────────────────────────

def setup_output(base_dir: Path):
    """Create timestamped folder and return (csv_path, run_folder)."""
    timestamp   = datetime.now().strftime("%Y-%m-%d_%H-%M")
    run_folder  = base_dir / "results" / f"{timestamp}_tnpcb"
    run_folder.mkdir(parents=True, exist_ok=True)
    csv_path    = run_folder / "tnpcb_signals.csv"
    return csv_path, run_folder


def update_latest(base_dir: Path, csv_path: Path):
    """Update results/latest.json with the path to this run's CSV."""
    latest_file = base_dir / "results" / "latest.json"
    latest = {}
    if latest_file.exists():
        try:
            latest = json.loads(latest_file.read_text())
        except Exception:
            pass
    latest["tnpcb"] = str(csv_path.relative_to(base_dir / "results"))
    latest_file.write_text(json.dumps(latest, indent=2))
    print(f"   ✅ latest.json updated → {latest['tnpcb']}")


# ── Scraping logic ────────────────────────────────────────────────

def find_group_ids():
    print("\n🔍 Finding groupIds for Kongu districts...")
    found = dict(KNOWN_REGIONS)

    for region_name in TARGET_REGIONS:
        region_param = region_name.replace(" ", "+")
        url = (
            f"{BASE}/OCMMS/allReports/searchDashboard2"
            f"?region={region_param}&fromDateStr={FROM_DATE}&toDateStr={TO_DATE}"
        )
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code != 200:
                print(f"   ⚠️  {region_name} — HTTP {r.status_code}")
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            group_id = None
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "groupId=" in href:
                    try:
                        gid = href.split("groupId=")[1].split("&")[0]
                        group_id = int(gid)
                        break
                    except Exception:
                        continue

            if group_id:
                found[region_name] = group_id
                print(f"   ✅ {region_name} → groupId={group_id}")
            else:
                print(f"   🔎 {region_name} — scanning nearby IDs...")
                for gid in range(100490, 100520):
                    test_url = (
                        f"{BASE}/OCMMS/allReports/elseShowApplicationsOnServiceDashboard"
                        f"?groupId={gid}&status=All&fromDateStr={FROM_DATE}&toDateStr={TO_DATE}"
                        f"&applicationType=CTE&days="
                    )
                    try:
                        tr = requests.get(test_url, headers=HEADERS, timeout=10)
                        ts = BeautifulSoup(tr.text, "html.parser")
                        page_text = ts.get_text()
                        if region_name.replace("DEE ", "").title() in page_text or region_name in page_text:
                            found[region_name] = gid
                            print(f"   ✅ {region_name} → groupId={gid} (scan)")
                            break
                        time.sleep(0.5)
                    except Exception:
                        continue
                else:
                    print(f"   ❌ {region_name} — could not find groupId")

        except Exception as e:
            print(f"   ❌ {region_name} — {e}")

        time.sleep(1.5)

    return found


def fetch_companies(group_id, region_name, app_type):
    url = (
        f"{BASE}/OCMMS/allReports/elseShowApplicationsOnServiceDashboard"
        f"?groupId={group_id}&status=All&fromDateStr={FROM_DATE}&toDateStr={TO_DATE}"
        f"&applicationType={app_type}&days="
    )
    companies = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        if r.status_code != 200:
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        for table in soup.find_all("table"):
            for tr in table.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if len(cells) >= 3:
                    app_no   = cells[0] if len(cells) > 0 else ""
                    app_date = cells[1] if len(cells) > 1 else ""
                    name     = cells[2] if len(cells) > 2 else ""
                    address  = cells[3] if len(cells) > 3 else ""
                    status   = cells[-1] if cells else ""

                    junk = (
                        not name or len(name) <= 3
                        or name.startswith("|")
                        or name.startswith("Application")
                        or "Summarise" in name
                        or "Print" in name
                        or "Industry" in name
                    )
                    if not junk:
                        companies.append({
                            "company_name":     name,
                            "industry_address": address,
                            "application_no":   app_no,
                            "application_date": app_date,
                            "application_type": app_type,
                            "status":           status,
                            "district":         region_name.replace("DEE ", "").title(),
                            "region":           region_name,
                            "signal_type":      "TNPCB Consent Application",
                            "source":           "ocmms.tn.gov.in",
                            "scraped_date":     datetime.now().strftime("%Y-%m-%d"),
                        })
        return companies

    except requests.exceptions.Timeout:
        print(f" timeout", end="")
        return []
    except Exception as e:
        print(f" error: {e}", end="")
        return []


# ── Entry point ───────────────────────────────────────────────────

def run(base_dir: Path = None):
    if base_dir is None:
        base_dir = Path(__file__).parent

    csv_path, run_folder = setup_output(base_dir)

    print("=" * 60)
    print("  TNPCB Scraper — Kongu Industrial Corridor")
    print("=" * 60)
    print(f"  Date range : {FROM_DATE} to {TO_DATE}")
    print(f"  Output     : {csv_path}")
    print("=" * 60)

    regions = find_group_ids()
    print(f"\n✅ Found {len(regions)} regions: {list(regions.keys())}")

    total = 0
    csvfile = open(csv_path, "w", newline="", encoding="utf-8")
    writer  = csv.DictWriter(csvfile, fieldnames=FIELDNAMES, extrasaction="ignore")
    writer.writeheader()

    try:
        for region_name, group_id in regions.items():
            print(f"\n📋 {region_name} (groupId={group_id})")
            for app_type in APPLICATION_TYPES:
                print(f"   → {app_type}...", end=" ", flush=True)
                companies = fetch_companies(group_id, region_name, app_type)
                for c in companies:
                    writer.writerow(c)
                    csvfile.flush()
                    total += 1
                print(f"✅ {len(companies)} companies" if companies else "— none")
                time.sleep(1.5)

    except KeyboardInterrupt:
        print("\n\n⚠️  Stopped by user.")
    finally:
        csvfile.close()

    print("\n" + "=" * 60)
    print(f"  Total saved : {total}")
    print(f"  File        : {csv_path}")
    print("=" * 60)

    update_latest(base_dir, csv_path)
    return str(csv_path)


if __name__ == "__main__":
    run()
