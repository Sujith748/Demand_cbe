"""
CCMC / onlineppa Building Plan Approvals Scraper
=================================================
Saves to: results/YYYY-MM-DD_HH-MM_ccmc/ccmc_signals.csv
Updates:  results/latest.json

Usage:
    pip install playwright pandas openpyxl && playwright install chromium
    python3 ccmc_scraper.py
"""

import asyncio
import os
import glob
import json
from datetime import datetime
from pathlib import Path
import pandas as pd
from playwright.async_api import async_playwright

URL            = "https://onlineppa.tn.gov.in/approved-plan-list"
DEPARTMENTS    = ["DTCP", "Rural Panchayat", "Town Panchayat"]
APPROVAL_TYPES = ["Layout Approval", "Building Plan"]
DISTRICTS      = ["Coimbatore", "Tiruppur", "Erode"]
YEARS          = ["2022", "2023", "2024", "2025", "2026"]


# ── Output folder setup ───────────────────────────────────────────

def setup_output(base_dir: Path):
    timestamp  = datetime.now().strftime("%Y-%m-%d_%H-%M")
    run_folder = base_dir / "results" / f"{timestamp}_ccmc"
    run_folder.mkdir(parents=True, exist_ok=True)
    csv_path     = run_folder / "ccmc_signals.csv"
    download_dir = run_folder / "excel_downloads"
    download_dir.mkdir(exist_ok=True)
    return csv_path, run_folder, download_dir


def update_latest(base_dir: Path, csv_path: Path):
    latest_file = base_dir / "results" / "latest.json"
    latest = {}
    if latest_file.exists():
        try:
            latest = json.loads(latest_file.read_text())
        except Exception:
            pass
    latest["ccmc"] = str(csv_path.relative_to(base_dir / "results"))
    latest_file.write_text(json.dumps(latest, indent=2))
    print(f"   ✅ latest.json updated → {latest['ccmc']}")


# ── Scraping logic ────────────────────────────────────────────────

async def inspect_dropdowns(page):
    await page.goto(URL, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(2000)
    print("\n=== DROPDOWN VALUES ===")
    for sel_name in ["depName", "appType", "district", "year"]:
        sel = page.locator(f"select[name='{sel_name}']")
        if await sel.count() > 0:
            opts = await sel.locator("option").all_inner_texts()
            print(f"  {sel_name}: {opts}")
        else:
            print(f"  {sel_name}: NOT a native select")


async def scrape_combination(page, dept, app_type, district, year, download_dir):
    print(f"  → {dept} | {app_type} | {district} | {year} ...", end=" ", flush=True)

    try:
        await page.goto(URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        await page.locator("select[name='depName']").select_option(label=dept)
        await page.wait_for_timeout(400)
        await page.locator("select[name='appType']").select_option(label=app_type)
        await page.wait_for_timeout(400)
        await page.locator("select[name='district']").select_option(label=district)
        await page.wait_for_timeout(400)
        await page.locator("select[name='year']").select_option(label=year)
        await page.wait_for_timeout(400)

        await page.click("#search")
        await page.wait_for_timeout(5000)

        table = page.locator("#example")
        rows  = await table.locator("tbody tr").count()

        if rows == 0:
            print("— no data")
            return None

        print(f"{rows} rows", end=" ", flush=True)

        fname     = f"ccmc_{dept}_{app_type}_{district}_{year}.xlsx".replace(" ", "_")
        save_path = str(download_dir / fname)

        async with page.expect_download(timeout=30000) as dl:
            await page.locator(".buttons-excel, button:has-text('Excel'), a:has-text('Excel')").first.click()

        download = await dl.value
        await download.save_as(save_path)
        print(f"✅")
        return save_path

    except Exception as e:
        msg = str(e)[:80]
        print(f"— {msg}")
        return None


# ── Entry point ───────────────────────────────────────────────────

async def scrape(base_dir: Path = None):
    if base_dir is None:
        base_dir = Path(__file__).parent

    csv_path, run_folder, download_dir = setup_output(base_dir)

    print("=" * 60)
    print("  CCMC / onlineppa Building Plan Approvals Scraper")
    print("=" * 60)
    print(f"  Output : {csv_path}")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            downloads_path=str(download_dir),
        )
        context = await browser.new_context(accept_downloads=True)
        page    = await context.new_page()

        await inspect_dropdowns(page)

        total = 0
        for dept in DEPARTMENTS:
            print(f"\n{'='*40}\n  {dept}\n{'='*40}")
            for app_type in APPROVAL_TYPES:
                for district in DISTRICTS:
                    for year in YEARS:
                        result = await scrape_combination(page, dept, app_type, district, year, download_dir)
                        if result:
                            total += 1
                        await asyncio.sleep(1)

        print(f"\n\nTotal downloads: {total}")
        await browser.close()

    # Consolidate all Excel files into one CSV
    files = glob.glob(str(download_dir / "*.xlsx"))
    if files:
        print(f"\nConsolidating {len(files)} files...")
        dfs = []
        for f in files:
            try:
                df = pd.read_excel(f, engine="openpyxl")
                df = df.dropna(how="all")
                df["source_file"]  = os.path.basename(f)
                df["signal_type"]  = "Building Plan / Layout Approval"
                df["source"]       = "onlineppa.tn.gov.in"
                df["scraped_date"] = datetime.now().strftime("%Y-%m-%d")
                dfs.append(df)
                print(f"  {os.path.basename(f)}: {len(df)} rows")
            except Exception as e:
                print(f"  ⚠️  {os.path.basename(f)}: {e}")

        if dfs:
            out = pd.concat(dfs, ignore_index=True).drop_duplicates()
            out.to_csv(csv_path, index=False)
            print(f"\n✅ {len(out)} rows → {csv_path}")
        else:
            print("\n⚠️  No Excel files could be parsed.")
    else:
        print("\n⚠️  No Excel files downloaded.")

    update_latest(base_dir, csv_path)
    return str(csv_path)


def run(base_dir: Path = None):
    asyncio.run(scrape(base_dir))


if __name__ == "__main__":
    run()
