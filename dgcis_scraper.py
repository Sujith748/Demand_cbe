"""
DGCIS Trade Scraper — ICD Irugur (Coimbatore)
==============================================
Saves to: results/YYYY-MM-DD_HH-MM_dgcis/dgcis_signals.csv
Updates:  results/latest.json

Usage:
    pip install playwright && playwright install chromium
    python3 dgcis_scraper.py
"""

import asyncio
import csv
import json
import os
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Page

URL       = "https://ftddp.dgciskol.gov.in/dgcis/principalcommditysearch.html#!/freeuser"
DEBUG_DIR = "debug_screenshots"

DATE_WINDOWS = [
    ("Apr-2025", "Mar-2026", "FY2025-26"),
    ("Apr-2024", "Mar-2025", "FY2024-25"),
    ("Apr-2023", "Mar-2024", "FY2023-24"),
]

FIELDNAMES = [
    "period", "trade_type", "commodity", "country", "port",
    "quantity", "unit", "value_inr_lakh", "signal_type", "source", "scraped_date",
]


# ── Output folder setup ───────────────────────────────────────────

def setup_output(base_dir: Path):
    timestamp  = datetime.now().strftime("%Y-%m-%d_%H-%M")
    run_folder = base_dir / "results" / f"{timestamp}_dgcis"
    run_folder.mkdir(parents=True, exist_ok=True)
    csv_path   = run_folder / "dgcis_signals.csv"
    # Debug screenshots go inside the run folder
    debug_dir  = run_folder / "debug_screenshots"
    debug_dir.mkdir(exist_ok=True)
    return csv_path, run_folder, debug_dir


def update_latest(base_dir: Path, csv_path: Path):
    latest_file = base_dir / "results" / "latest.json"
    latest = {}
    if latest_file.exists():
        try:
            latest = json.loads(latest_file.read_text())
        except Exception:
            pass
    latest["dgcis"] = str(csv_path.relative_to(base_dir / "results"))
    latest_file.write_text(json.dumps(latest, indent=2))
    print(f"   ✅ latest.json updated → {latest['dgcis']}")


# ── AngularJS helpers ─────────────────────────────────────────────

async def ng_set_select(page: Page, select_index: int, target_value: str) -> bool:
    result = await page.evaluate(f"""({{idx, val}}) => {{
        const selects = Array.from(document.querySelectorAll('select')).filter(s => !s.getAttribute('ng-model'));
        const el = selects[idx];
        if (!el) return 'NOT_FOUND';
        let matched = null;
        for (const opt of el.options) {{
            if (opt.text.trim().toUpperCase().includes(val.toUpperCase())) {{
                matched = opt; break;
            }}
        }}
        if (!matched) return 'NO_OPTION:' + Array.from(el.options).map(o=>o.text).join('|');
        el.value = matched.value;
        try {{
            const ng = angular.element(el);
            ng.triggerHandler('change');
            angular.element(document.body).injector().get('$rootScope').$apply();
        }} catch(e) {{
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
        }}
        return 'OK:' + matched.text;
    }}""", {"idx": select_index, "val": target_value})

    if result and result.startswith("OK:"):
        print(f"   ✅ select[{select_index}] → {result[3:]}")
        return True
    else:
        print(f"   ⚠️  select[{select_index}] failed: {result}")
        return False


async def ng_set_date(page: Page, ng_model: str, value: str) -> bool:
    result = await page.evaluate(f"""({{model, val}}) => {{
        const el = document.querySelector("input[ng-model='" + model + "']");
        if (!el) return 'NOT_FOUND';
        try {{
            const scope = angular.element(el).scope();
            scope[model] = val;
            scope.$apply();
            return 'OK_SCOPE';
        }} catch(e) {{
            try {{
                angular.element(el).val(val).triggerHandler('input').triggerHandler('change');
                return 'OK_TRIGGER';
            }} catch(e2) {{
                return 'ERROR:' + e2;
            }}
        }}
    }}""", {"model": ng_model, "val": value})

    if result and result.startswith("OK"):
        print(f"   ✅ date ng-model='{ng_model}' → {value}")
        return True
    else:
        print(f"   ⚠️  date ng-model='{ng_model}' failed: {result}")
        return False


async def setup_filters(page: Page, debug_dir: Path) -> bool:
    await page.screenshot(path=str(debug_dir / "before_filters.png"))

    print("   Setting Commodity → ALL VALUE...")
    await ng_set_select(page, 0, "ALL VALUE")
    await page.wait_for_timeout(400)

    print("   Setting Country → ALL VALUE...")
    await ng_set_select(page, 1, "ALL VALUE")
    await page.wait_for_timeout(400)

    port_set = False
    print("   Setting Port → ICD IRUGUR...")
    for pname in ["ICD IRUGUR", "ICD IRGUR", "IRUGUR", "IRGUR"]:
        if await ng_set_select(page, 2, pname):
            port_set = True
            break

    if not port_set:
        print("   ⚠️  Port not set — will filter post-scrape")

    await page.screenshot(path=str(debug_dir / "after_filters.png"))
    return port_set


async def extract_table(page: Page, period: str, trade_type: str, debug_dir: Path) -> list:
    rows = []
    try:
        found = False
        for _ in range(20):
            await page.wait_for_timeout(1000)
            if await page.locator("table tbody tr").count() > 0:
                found = True
                break
            if await page.locator("text=No Record Found").count() > 0:
                print("   ℹ️  No records found")
                return []

        if not found:
            print("   ⚠️  Timed out waiting for table")
            await page.screenshot(path=str(debug_dir / f"timeout_{trade_type}_{period}.png"))
            return []

        all_tables = page.locator("table")
        table_count = await all_tables.count()
        best_idx, best_count = 0, 0
        for i in range(table_count):
            n = await all_tables.nth(i).locator("tbody tr").count()
            if n > best_count:
                best_count, best_idx = n, i

        print(f"   Using table {best_idx} with {best_count} rows")
        trs = await all_tables.nth(best_idx).locator("tbody tr").all()

        skip_texts = {"", "sl.no", "s.no", "total", "commodity", "#", "no.", "sr.no"}
        for tr in trs:
            cells = await tr.locator("td").all_inner_texts()
            cells = [c.strip() for c in cells]
            if not cells or cells[0].lower() in skip_texts:
                continue
            rows.append({
                "period":         period,
                "trade_type":     trade_type,
                "commodity":      cells[0] if len(cells) > 0 else "",
                "country":        cells[1] if len(cells) > 1 else "",
                "port":           cells[2] if len(cells) > 2 else "",
                "quantity":       cells[3] if len(cells) > 3 else "",
                "unit":           cells[4] if len(cells) > 4 else "",
                "value_inr_lakh": cells[5] if len(cells) > 5 else "",
                "signal_type":    "DGCIS Trade Data — ICD Irugur",
                "source":         "ftddp.dgciskol.gov.in",
                "scraped_date":   datetime.now().strftime("%Y-%m-%d"),
            })

        irugur = [r for r in rows if any(x in r["port"].upper() for x in ["IRUGUR", "IRGUR"])]
        if irugur:
            print(f"   ICD Irugur rows: {len(irugur)} of {len(rows)}")
            return irugur
        print(f"   ℹ️  No Irugur port rows — returning all {len(rows)}")
        return rows

    except Exception as e:
        print(f"   ❌ Table error: {e}")
        await page.screenshot(path=str(debug_dir / f"error_{trade_type}_{period}.png"))
        return []


async def run_query(page: Page, from_date: str, to_date: str,
                    period: str, trade_type: str, radio_val: str,
                    debug_dir: Path) -> list:
    print(f"\n  ▶ {trade_type} | {period} ({from_date} → {to_date})")

    await page.goto(URL, wait_until="networkidle", timeout=60000)
    await page.wait_for_timeout(3000)

    await ng_set_date(page, "datepicker",  from_date)
    await ng_set_date(page, "datepicker1", to_date)
    await page.wait_for_timeout(500)

    radio = page.locator(f"input[type='radio'][value='{radio_val}']")
    if await radio.count() > 0:
        await radio.first.click()
        print(f"   ✅ Radio: {trade_type}")
    await page.wait_for_timeout(300)

    report_sel = page.locator("select[ng-model='type']")
    if await report_sel.count() > 0:
        await report_sel.first.select_option(label="COMMODITY BY COUNTRY BY PORT")
        print("   ✅ Report type set")
    await page.wait_for_timeout(1500)

    await setup_filters(page, debug_dir)
    await page.wait_for_timeout(500)

    execute_btn = page.locator("button:has-text('Execute Query'), button:has-text('Execute'), button:has-text('Search')")
    if await execute_btn.count() > 0:
        await execute_btn.first.click()
        print("   ⏳ Executing query...")
    else:
        print("   ❌ Execute button not found")
        return []

    return await extract_table(page, period, trade_type, debug_dir)


# ── Entry point ───────────────────────────────────────────────────

async def scrape(base_dir: Path = None):
    if base_dir is None:
        base_dir = Path(__file__).parent

    csv_path, run_folder, debug_dir = setup_output(base_dir)

    print("=" * 60)
    print("  DGCIS Scraper — ICD Irugur, Coimbatore")
    print("=" * 60)
    print(f"  Output     : {csv_path}")
    print(f"  Debug shots: {debug_dir}")
    print("=" * 60)

    all_rows = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=80)
        context = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            accept_downloads=True,
        )
        page = await context.new_page()

        for trade_type, radio_val in [("Export", "E"), ("Import", "I")]:
            print(f"\n{'='*40}\n  {trade_type}\n{'='*40}")
            for from_date, to_date, period in DATE_WINDOWS:
                rows = await run_query(page, from_date, to_date, period, trade_type, radio_val, debug_dir)
                if rows:
                    all_rows.extend(rows)
                    print(f"   ✅ {len(rows)} rows — {period}")
                    break
                print(f"   → No data for {period}, trying earlier period...")

        await browser.close()

    if all_rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            w.writeheader()
            w.writerows(all_rows)
        print(f"\n✅ {len(all_rows)} rows → {csv_path}")
        from collections import Counter
        print("\n📊 TOP COMMODITIES AT ICD IRUGUR:")
        for c, n in Counter(r["commodity"] for r in all_rows).most_common(10):
            print(f"   {n:4d}  {c[:60]}")
    else:
        print("\n⚠️  No data. Check debug_screenshots/ in the run folder.")

    update_latest(base_dir, csv_path)
    return str(csv_path)


def run(base_dir: Path = None):
    asyncio.run(scrape(base_dir))


if __name__ == "__main__":
    run()
