"""
TN Online PPA — Approved Plan List Scraper
==========================================
Focused on: Coimbatore district only
Saves to:   results/YYYY-MM-DD_HH-MM_ppa/tn_ppa_approved_plans.csv
Updates:    results/latest.json

Usage:
    pip install playwright openpyxl && playwright install chromium
    python3 tn_ppa_scraper.py
"""

import asyncio
import csv
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

PAGE_URL = "https://onlineppa.tn.gov.in/approved-plan-list"

SEARCH_COMBINATIONS = [
    ("DTCP",            "Layout Approval"),
    ("DTCP",            "Building Plan"),
    ("Rural Panchayat", "Layout Approval"),
    ("Rural Panchayat", "Building Plan"),
    ("Town Panchayat",  "Layout Approval"),
    ("Town Panchayat",  "Building Plan"),
]

YEARS = ["2025", "2024", "2023", "2022"]

FIELDNAMES = [
    "s_no", "application_no", "district", "approval_type",
    "permit_issue_date", "total_fees", "approval_no",
    "department", "year", "source", "scraped_date",
]


# ── Output folder setup ───────────────────────────────────────────

def setup_output(base_dir: Path):
    timestamp  = datetime.now().strftime("%Y-%m-%d_%H-%M")
    run_folder = base_dir / "results" / f"{timestamp}_ppa"
    run_folder.mkdir(parents=True, exist_ok=True)
    csv_path   = run_folder / "tn_ppa_approved_plans.csv"
    return csv_path, run_folder


def update_latest(base_dir: Path, csv_path: Path):
    latest_file = base_dir / "results" / "latest.json"
    latest = {}
    if latest_file.exists():
        try:
            latest = json.loads(latest_file.read_text())
        except Exception:
            pass
    latest["ppa"] = str(csv_path.relative_to(base_dir / "results"))
    latest_file.write_text(json.dumps(latest, indent=2))
    print(f"   ✅ latest.json updated → {latest['ppa']}")


# ── JS helpers ────────────────────────────────────────────────────

async def js_set(page, select_id, label_or_value, by="label"):
    result = await page.evaluate("""({ id, target, by }) => {
        const sel = document.getElementById(id) || document.querySelector('[name="'+id+'"]');
        if (!sel) return 'not_found';
        const opts = Array.from(sel.options);
        const match = by === 'label'
            ? opts.find(o => o.text.trim().toLowerCase() === target.toLowerCase())
            : opts.find(o => o.value === target);
        if (!match) return 'no_match:' + opts.map(o=>o.text.trim()).join('|');
        sel.value = match.value;
        ['input','change'].forEach(e => sel.dispatchEvent(new Event(e, {bubbles:true})));
        try { angular.element(sel).triggerHandler('change'); } catch(e) {}
        return 'ok:' + match.value;
    }""", {"id": select_id, "target": label_or_value, "by": by})
    ok = result and result.startswith("ok")
    print(f"   {'✅' if ok else '⚠️ '} {select_id} = '{label_or_value}' → {result}")
    await page.wait_for_timeout(500)
    return ok


async def js_click_search(page):
    result = await page.evaluate("""() => {
        const btns = Array.from(document.querySelectorAll('button, input[type=submit]'));
        const search = btns.find(b =>
            b.textContent.trim().toLowerCase().includes('search') ||
            (b.value || '').toLowerCase().includes('search')
        );
        if (search) { search.click(); return 'clicked:' + search.tagName; }
        const form = document.querySelector('form');
        if (form) { form.submit(); return 'form_submit'; }
        return 'not_found';
    }""")
    print(f"   🔘 Search click: {result}")
    return result and result != "not_found"


async def wait_for_table(page, timeout=20000):
    try:
        await page.wait_for_selector("table tbody tr td", timeout=timeout)
        await page.wait_for_timeout(500)
        return True
    except Exception:
        return False


async def download_excel(page, dept, plan_type, year, download_dir):
    fname = f"ppa_{dept}_{plan_type}_{year}.xlsx".replace(" ", "_")
    fpath = Path(download_dir) / fname
    try:
        async with page.expect_download(timeout=30000) as dl_info:
            result = await page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button, a, input'));
                const excel = btns.find(b =>
                    b.textContent.trim().toLowerCase() === 'excel' ||
                    (b.value || '').toLowerCase() === 'excel'
                );
                if (excel) { excel.click(); return 'clicked'; }
                return 'not_found';
            }""")
            if result == "not_found":
                return None
        download = await dl_info.value
        await download.save_as(str(fpath))
        print(f"   📥 Excel downloaded: {fname}")
        return str(fpath)
    except Exception as e:
        print(f"   ⚠️  Excel download failed: {e}")
        return None


async def scrape_html_table(page, dept, plan_type, year):
    rows = []
    page_num = 1
    while True:
        body_text = await page.locator("body").inner_text()
        if any(x in body_text.lower() for x in ["no data", "no record", "no entries found", "0 entries"]):
            print(f"   (no records)")
            break

        tbl = page.locator("table").first
        if await tbl.count() == 0:
            break

        trs = await tbl.locator("tbody tr").all()
        if not trs:
            break

        print(f"   📄 Page {page_num}: {len(trs)} rows")
        for tr in trs:
            cells = await tr.locator("td").all_inner_texts()
            cells = [c.strip() for c in cells]
            if not cells or not cells[0] or not cells[0].replace(".", "").isdigit():
                continue
            rows.append({
                "s_no":              cells[0]  if len(cells) > 0 else "",
                "application_no":    cells[1]  if len(cells) > 1 else "",
                "district":          cells[2]  if len(cells) > 2 else "Coimbatore",
                "approval_type":     cells[3]  if len(cells) > 3 else plan_type,
                "permit_issue_date": cells[4]  if len(cells) > 4 else "",
                "total_fees":        cells[5]  if len(cells) > 5 else "",
                "approval_no":       cells[7]  if len(cells) > 7 else "",
                "department":        dept,
                "year":              year,
                "source":            PAGE_URL,
                "scraped_date":      datetime.now().strftime("%Y-%m-%d"),
            })

        next_btn = page.locator("a:has-text('Next'), button:has-text('Next')").first
        if await next_btn.count() == 0:
            break
        cls      = await next_btn.get_attribute("class") or ""
        disabled = await next_btn.get_attribute("disabled")
        if disabled or "disabled" in cls:
            break

        await next_btn.click()
        if not await wait_for_table(page):
            break
        page_num += 1

    return rows


def parse_excel(fpath, dept, plan_type, year):
    try:
        import openpyxl
        wb = openpyxl.load_workbook(fpath)
        ws = wb.active
        rows = []
        headers = None
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                headers = [str(c).strip().lower() if c else "" for c in row]
                continue
            if not row or not row[0]:
                continue
            r = dict(zip(headers, [str(c).strip() if c else "" for c in row]))
            rows.append({
                "s_no":              r.get("s.no", r.get("sno", str(i))),
                "application_no":    r.get("application no", r.get("applicationno", "")),
                "district":          r.get("district", "Coimbatore"),
                "approval_type":     r.get("approval type", plan_type),
                "permit_issue_date": r.get("permit issue date", r.get("permitissuedate", "")),
                "total_fees":        r.get("total fees", r.get("totalfees", "")),
                "approval_no":       r.get("approval no", r.get("approvalno", "")),
                "department":        dept,
                "year":              year,
                "source":            PAGE_URL,
                "scraped_date":      datetime.now().strftime("%Y-%m-%d"),
            })
        print(f"   📊 Parsed {len(rows)} rows from Excel")
        return rows
    except ImportError:
        print("   ℹ️  openpyxl not installed — pip install openpyxl")
        return []
    except Exception as e:
        print(f"   ⚠️  Excel parse error: {e}")
        return []


async def run_one(page, dept, plan_type, year, download_dir):
    print(f"\n{'─'*55}")
    print(f"  {dept} | {plan_type} | Coimbatore | {year}")
    print(f"{'─'*55}")

    await page.goto(PAGE_URL, wait_until="networkidle", timeout=60000)
    await page.wait_for_timeout(1500)

    await js_set(page, "depName",  dept,      by="label")
    await js_set(page, "appType",  plan_type, by="label")
    await js_set(page, "district", "DST_004", by="value")  # Coimbatore
    await js_set(page, "year",     year,      by="label")

    clicked = await js_click_search(page)
    if not clicked:
        btn = page.locator("button.btn-success, button.btn-primary, button:has-text('Search')").first
        if await btn.count() > 0:
            await btn.click(force=True)

    has_data = await wait_for_table(page)
    if not has_data:
        print("   (no records)")
        return []

    excel_path = await download_excel(page, dept, plan_type, year, download_dir)
    if excel_path:
        rows = parse_excel(excel_path, dept, plan_type, year)
        if rows:
            return rows

    print("   ↩️  Falling back to HTML pagination...")
    return await scrape_html_table(page, dept, plan_type, year)


# ── Entry point ───────────────────────────────────────────────────

async def scrape(base_dir: Path = None):
    if base_dir is None:
        base_dir = Path(__file__).parent

    csv_path, run_folder = setup_output(base_dir)
    download_dir = run_folder / "excel_downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 55)
    print("  TN Online PPA — Coimbatore Approved Plans")
    print("=" * 55)
    print(f"  Output : {csv_path}")
    print("=" * 55)

    all_rows = []
    seen     = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            downloads_path=str(download_dir),
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            accept_downloads=True,
        )
        page = await context.new_page()

        for dept, plan_type in SEARCH_COMBINATIONS:
            for year in YEARS:
                rows = await run_one(page, dept, plan_type, year, download_dir)
                new = 0
                for r in rows:
                    uid = r["application_no"] or f"{r['permit_issue_date']}|{r['approval_no']}"
                    if uid and uid not in seen:
                        seen.add(uid)
                        all_rows.append(r)
                        new += 1
                if new:
                    print(f"   ✅ +{new} new rows (total: {len(all_rows)})")

        await browser.close()

    if all_rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            w.writeheader()
            w.writerows(all_rows)
        print(f"\n✅ {len(all_rows)} rows saved → {csv_path}")
    else:
        print("\n⚠️  No data extracted.")

    update_latest(base_dir, csv_path)
    return str(csv_path)


def run(base_dir: Path = None):
    asyncio.run(scrape(base_dir))


if __name__ == "__main__":
    run()
