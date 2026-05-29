"""
Udyam MSME Scraper — Kongu Industrial Corridor (v2)
====================================================
Saves to: results/YYYY-MM-DD_HH-MM_udyam/udyam_signals.csv
Updates:  results/latest.json

Usage:
    python3 udyam_scraper.py
"""

import requests
from bs4 import BeautifulSoup
import csv
import time
import json
import os
from datetime import datetime
from pathlib import Path

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}

DISTRICTS = {
    "695": "Coimbatore",
    "697": "Tirupur",
    "693": "Erode",
}

NIC_CODES = {
    "28131": "Pumps for liquids",
    "28132": "Pumps for other uses",
    "28210": "General purpose machinery",
    "28220": "Machine tools",
    "28290": "Other general machinery",
    "27501": "Domestic appliances (wet grinders)",
    "29301": "Auto components",
    "25110": "Metal structures & fabrication",
    "25990": "Other fabricated metal products",
    "24310": "Casting of iron & steel",
    "22190": "Rubber products",
    "22209": "Plastic products",
    "10610": "Grain milling",
    "10890": "Other food products",
    "17021": "Corrugated paper & packaging",
}

FIELDNAMES = [
    "company_name", "district", "pincode", "address",
    "industry", "nic_code", "category",
    "signal_type", "source", "scraped_date",
]


# ── Output folder setup ───────────────────────────────────────────

def setup_output(base_dir: Path):
    timestamp  = datetime.now().strftime("%Y-%m-%d_%H-%M")
    run_folder = base_dir / "results" / f"{timestamp}_udyam"
    run_folder.mkdir(parents=True, exist_ok=True)
    csv_path   = run_folder / "udyam_signals.csv"
    return csv_path, run_folder


def update_latest(base_dir: Path, csv_path: Path):
    latest_file = base_dir / "results" / "latest.json"
    latest = {}
    if latest_file.exists():
        try:
            latest = json.loads(latest_file.read_text())
        except Exception:
            pass
    latest["udyam"] = str(csv_path.relative_to(base_dir / "results"))
    latest_file.write_text(json.dumps(latest, indent=2))
    print(f"   ✅ latest.json updated → {latest['udyam']}")


# ── Scraping logic ────────────────────────────────────────────────

def fetch_companies(nic_code, district_code, district_name, nic_desc):
    url = (
        f"https://udyamregistration.gov.in/SearchRegDetail.aspx"
        f"?cod={nic_code}&ty=2&si=33&di={district_code}"
    )

    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code != 200:
                return []

            soup = BeautifulSoup(r.text, "html.parser")
            companies = []

            for table in soup.find_all("table"):
                for tr in table.find_all("tr")[1:]:
                    cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                    if len(cells) >= 4:
                        name = cells[1] if len(cells) > 1 else ""
                        if name and "No results" not in name:
                            companies.append({
                                "company_name": name,
                                "address":      cells[2] if len(cells) > 2 else "",
                                "district":     district_name,
                                "pincode":      cells[5] if len(cells) > 5 else "",
                                "category":     cells[6] if len(cells) > 6 else "",
                                "nic_code":     nic_code,
                                "industry":     nic_desc,
                                "signal_type":  "Udyam Registration",
                                "source":       "udyamregistration.gov.in",
                                "scraped_date": datetime.now().strftime("%Y-%m-%d"),
                            })
            return companies

        except requests.exceptions.Timeout:
            if attempt == 0:
                print(f" timeout, retrying...", end=" ", flush=True)
                time.sleep(3)
            else:
                return []
        except KeyboardInterrupt:
            raise
        except Exception:
            return []

    return []


# ── Entry point ───────────────────────────────────────────────────

def run(base_dir: Path = None):
    if base_dir is None:
        base_dir = Path(__file__).parent

    csv_path, run_folder = setup_output(base_dir)

    print("=" * 60)
    print("  Udyam Scraper v2 — Kongu Industrial Corridor")
    print("=" * 60)
    print(f"  Districts : {', '.join(DISTRICTS.values())}")
    print(f"  NIC codes : {len(NIC_CODES)}")
    print(f"  Output    : {csv_path}")
    print("  (Safe to Ctrl+C anytime — data saves as it goes)")
    print("=" * 60)

    total = 0
    seen  = set()

    csvfile = open(csv_path, "w", newline="", encoding="utf-8")
    writer  = csv.DictWriter(csvfile, fieldnames=FIELDNAMES, extrasaction="ignore")
    writer.writeheader()

    try:
        for nic_code, nic_desc in NIC_CODES.items():
            print(f"\n📦 {nic_desc} (NIC {nic_code})")

            for district_code, district_name in DISTRICTS.items():
                print(f"   → {district_name}...", end=" ", flush=True)

                companies = fetch_companies(nic_code, district_code, district_name, nic_desc)

                new = 0
                for c in companies:
                    key = (c["company_name"].lower().strip(), c["district"])
                    if key not in seen:
                        seen.add(key)
                        writer.writerow(c)
                        csvfile.flush()
                        new += 1
                        total += 1

                print(f"✅ {new}" if new else "— none")
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
