"""
Kongu Industrial Signal Dashboard
==================================
Run:
    pip install flask pandas beautifulsoup4 requests
    python app.py

Opens at: http://localhost:5000

Data lives in:
    results/
    ├── latest.json                    ← always points to newest file per source
    ├── 2026-05-29_10-29_tnpcb/
    │   └── tnpcb_signals.csv
    ├── 2026-05-29_10-36_udyam/
    │   └── udyam_signals.csv
    └── ...
"""

import os
import sys
import json
import threading
import webbrowser
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, render_template_string, request

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
RESULTS_DIR = BASE_DIR / "results"
LATEST_FILE = RESULTS_DIR / "latest.json"

SCRAPERS = {
    "tnpcb": BASE_DIR / "tnpcb_scraper.py",
    "udyam": BASE_DIR / "udyam_scraper.py",
    "ppa":   BASE_DIR / "tn_ppa_scraper.py",
    "dgcis": BASE_DIR / "dgcis_scraper.py",
    "ccmc":  BASE_DIR / "ccmc_scraper.py",
}

# Keys that each scraper writes into latest.json
SOURCE_KEYS = {
    "tnpcb": "tnpcb",
    "udyam": "udyam",
    "ppa":   "ppa",
    "dgcis": "dgcis",
    "ccmc":  "ccmc",
}

# Make sure results folder exists
RESULTS_DIR.mkdir(exist_ok=True)

# Track running scrapers
scraper_status = {}
scraper_log    = {}

app = Flask(__name__)


# ── Latest file resolver ────────────────────────────────────────────────────────

def get_latest_csv(source_key: str):
    """Read latest.json and return the Path to the most recent CSV for this source."""
    if not LATEST_FILE.exists():
        return None
    try:
        latest = json.loads(LATEST_FILE.read_text())
        rel    = latest.get(source_key)
        if not rel:
            return None
        p = RESULTS_DIR / rel
        return p if p.exists() else None
    except Exception:
        return None


def get_all_latest() -> dict:
    """Return dict of source_key -> Path (or None) for all sources."""
    if not LATEST_FILE.exists():
        return {k: None for k in SOURCE_KEYS}
    try:
        latest = json.loads(LATEST_FILE.read_text())
        result = {}
        for key in SOURCE_KEYS:
            rel = latest.get(key)
            if rel:
                p = RESULTS_DIR / rel
                result[key] = p if p.exists() else None
            else:
                result[key] = None
        return result
    except Exception:
        return {k: None for k in SOURCE_KEYS}


# ── Scoring logic ──────────────────────────────────────────────────────────────
NON_MFG_KEYWORDS = [
    "REALTY", "BUILDERS", "SHELTERS", "PROMOTERS", "INFRA MAT",
    "BLUE METALS", "M-SAND", "M SAND", "MSAND", "HATCHERIES",
    "CREMATORIUM", "MUNICIPALITY", "PANCHAYAT", "ACADEMY",
    "INSTITUTE", "TRUST", "DEVELOPERS LLP", "STONE CRUSHER",
    "CRUSHER", "SEWAGE", "BRICKS", "INFINIUM",
]

def is_manufacturing(name):
    n = str(name).upper()
    return not any(kw in n for kw in NON_MFG_KEYWORDS)


def load_tnpcb():
    f = get_latest_csv("tnpcb")
    if not f:
        return pd.DataFrame()
    df = pd.read_csv(f)
    df["app_date"] = pd.to_datetime(df["application_date"], dayfirst=True, errors="coerce")
    return df


def load_udyam():
    f = get_latest_csv("udyam")
    if not f:
        return pd.DataFrame()
    df = pd.read_csv(f)
    df = df[~df["company_name"].astype(str).str.match(r"^\d+$")]
    return df


def compute_top10():
    df = load_tnpcb()
    if df.empty:
        return []

    cte = df[df["application_type"] == "CTE"].copy()
    cte["is_mfg"] = cte["company_name"].apply(is_manufacturing)
    repeat = cte["company_name"].value_counts().to_dict()
    cte["repeat"] = cte["company_name"].map(repeat)
    cutoff = datetime.now() - timedelta(days=90)
    cte["recent"] = (cte["app_date"] >= cutoff).astype(int)
    cte["score"]  = (cte["is_mfg"].astype(int) * 3) + (cte["recent"] * 2) + cte["repeat"].clip(1, 5)

    top = (
        cte[cte["is_mfg"]]
        .sort_values(["score", "app_date"], ascending=[False, False])
        .drop_duplicates("company_name")
        .head(10)
    )

    results = []
    for i, (_, row) in enumerate(top.iterrows()):
        r = int(row["repeat"])
        reasons = []
        if r >= 6:
            reasons.append(f"🔴 {r} simultaneous CTE filings — aggressive multi-plant expansion")
        elif r >= 2:
            reasons.append(f"🟠 {r} CTE applications — multi-unit expansion confirmed")
        else:
            reasons.append("🟡 New CTE filed — facility establishment, space needed in 9–18 months")
        reasons.append(f"Filed {row['application_date']} — TNPCB consent precedes every financial signal")
        reasons.append(f"Location: {row['district']} — active Kongu manufacturing corridor")
        if row["recent"]:
            reasons.append("⚡ Filed within last 90 days — window is open right now")

        results.append({
            "rank":      i + 1,
            "name":      row["company_name"],
            "district":  row["district"],
            "date":      row["application_date"],
            "signal":    "TNPCB CTE",
            "score":     int(row["score"]),
            "repeat":    r,
            "reasons":   reasons,
            "action":    "Call within 7 days — you know before any broker does.",
            "lead_time": "9–18 months",
        })
    return results


def compute_stats():
    df_t = load_tnpcb()
    df_u = load_udyam()
    all_latest = get_all_latest()

    stats = {
        "tnpcb_total":  len(df_t),
        "tnpcb_cte":    int((df_t["application_type"] == "CTE").sum()) if not df_t.empty else 0,
        "tnpcb_recent": 0,
        "udyam_total":  len(df_u),
        "regions":      {},
        "industries":   {},
        "sources":      {},
        "last_scraped": {},
        "run_folders":  {},
    }

    if not df_t.empty:
        cutoff    = datetime.now() - timedelta(days=90)
        cte       = df_t[df_t["application_type"] == "CTE"]
        cte_dates = pd.to_datetime(cte["application_date"], dayfirst=True, errors="coerce")
        stats["tnpcb_recent"] = int((cte_dates >= cutoff).sum())
        stats["regions"]      = df_t["region"].value_counts().to_dict()

    if not df_u.empty:
        stats["industries"] = df_u["industry"].value_counts().head(5).to_dict()

    for key, path in all_latest.items():
        if path and path.exists():
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            stats["last_scraped"][key] = mtime.strftime("%d %b %Y, %H:%M")
            stats["sources"][key]      = "ok"
            stats["run_folders"][key]  = path.parent.name
        else:
            stats["last_scraped"][key] = "Never"
            stats["sources"][key]      = "missing"
            stats["run_folders"][key]  = ""

    return stats


def compute_pipeline():
    df = load_tnpcb()
    if df.empty:
        return []
    cte    = df[df["application_type"] == "CTE"].copy()
    cte    = cte[cte["company_name"].apply(is_manufacturing)]
    cte    = cte.sort_values("app_date", ascending=False).drop_duplicates("company_name")
    repeat = df[df["application_type"] == "CTE"]["company_name"].value_counts().to_dict()
    cte["repeat"] = cte["company_name"].map(repeat).fillna(1).astype(int)
    rows = []
    for _, r in cte.head(50).iterrows():
        rows.append({
            "name":     r["company_name"],
            "district": r["district"],
            "date":     r["application_date"],
            "repeat":   int(r["repeat"]),
            "type":     r["application_type"],
        })
    return rows


def list_all_runs():
    """Return list of all run folders with metadata."""
    if not RESULTS_DIR.exists():
        return []
    runs = []
    for folder in sorted(RESULTS_DIR.iterdir(), reverse=True):
        if not folder.is_dir():
            continue
        csvs = list(folder.glob("*.csv"))
        runs.append({
            "folder":    folder.name,
            "files":     [f.name for f in csvs],
            "file_count": len(csvs),
        })
    return runs[:20]  # last 20 runs


# ── Scraper runner ─────────────────────────────────────────────────────────────
def run_scraper_bg(source):
    script = SCRAPERS.get(source)
    if not script or not script.exists():
        scraper_status[source] = "error"
        scraper_log[source]    = f"Script not found: {script}"
        return

    scraper_status[source] = "running"
    scraper_log[source]    = "Starting..."
    try:
        proc = subprocess.Popen(
            [sys.executable, str(script)],
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for line in proc.stdout:
            scraper_log[source] = line.strip()
        proc.wait()
        if proc.returncode == 0:
            scraper_status[source] = "done"
            scraper_log[source]    = "Completed successfully"
        else:
            scraper_status[source] = "error"
            scraper_log[source]    = f"Exited with code {proc.returncode}"
    except Exception as e:
        scraper_status[source] = "error"
        scraper_log[source]    = str(e)


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/summary")
def api_summary():
    return jsonify({
        "top10":    compute_top10(),
        "stats":    compute_stats(),
        "pipeline": compute_pipeline(),
    })


@app.route("/api/runs")
def api_runs():
    return jsonify(list_all_runs())


@app.route("/api/scrape/<source>", methods=["POST"])
def api_scrape(source):
    if source not in SCRAPERS:
        return jsonify({"error": "Unknown source"}), 400
    if scraper_status.get(source) == "running":
        return jsonify({"status": "already_running"})
    t = threading.Thread(target=run_scraper_bg, args=(source,), daemon=True)
    t.start()
    return jsonify({"status": "started"})


@app.route("/api/scrape_status/<source>")
def api_scrape_status(source):
    return jsonify({
        "status": scraper_status.get(source, "idle"),
        "log":    scraper_log.get(source, ""),
    })


# ── HTML ───────────────────────────────────────────────────────────────────────
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kongu Signal Intelligence</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Sora:wght@300;400;500;600&display=swap');

  :root {
    --bg:      #0d0f12;
    --surface: #141720;
    --border:  #1e2330;
    --border2: #2a3045;
    --text:    #e8eaf0;
    --muted:   #6b7490;
    --accent:  #3d6fff;
    --accent2: #00c896;
    --warn:    #f5a623;
    --danger:  #e24b4a;
    --mono:    'DM Mono', monospace;
    --sans:    'Sora', sans-serif;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: var(--sans); font-size: 14px; min-height: 100vh; }

  .shell { display: grid; grid-template-columns: 220px 1fr; min-height: 100vh; }
  .sidebar { background: var(--surface); border-right: 1px solid var(--border); padding: 28px 0; display: flex; flex-direction: column; }
  .main { padding: 32px 36px; overflow-y: auto; }

  .logo { padding: 0 20px 28px; border-bottom: 1px solid var(--border); }
  .logo-tag { font-family: var(--mono); font-size: 9px; color: var(--muted); letter-spacing: .12em; text-transform: uppercase; margin-bottom: 4px; }
  .logo-title { font-size: 15px; font-weight: 600; color: var(--text); line-height: 1.3; }
  .nav { padding: 20px 0; flex: 1; }
  .nav-item { display: flex; align-items: center; gap: 10px; padding: 9px 20px; font-size: 13px; color: var(--muted); cursor: pointer; transition: all .15s; border-left: 2px solid transparent; }
  .nav-item:hover { color: var(--text); background: rgba(255,255,255,.03); }
  .nav-item.active { color: var(--accent); border-left-color: var(--accent); background: rgba(61,111,255,.06); }
  .nav-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--muted); flex-shrink: 0; }
  .nav-item.active .nav-dot { background: var(--accent); }
  .sidebar-bottom { padding: 20px; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 8px; }
  .refresh-btn { width: 100%; background: rgba(61,111,255,.1); border: 1px solid rgba(61,111,255,.25); color: var(--accent); font-family: var(--sans); font-size: 12px; padding: 9px; border-radius: 6px; cursor: pointer; transition: all .15s; }
  .refresh-btn:hover { background: rgba(61,111,255,.2); }

  .page { display: none; }
  .page.active { display: block; }

  .page-header { margin-bottom: 28px; }
  .page-label { font-family: var(--mono); font-size: 10px; color: var(--muted); letter-spacing: .1em; text-transform: uppercase; margin-bottom: 6px; }
  .page-title { font-size: 22px; font-weight: 600; color: var(--text); }
  .page-sub { font-size: 13px; color: var(--muted); margin-top: 4px; }

  .stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 32px; }
  .stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 18px 20px; }
  .stat-label { font-family: var(--mono); font-size: 10px; color: var(--muted); letter-spacing: .08em; text-transform: uppercase; margin-bottom: 8px; }
  .stat-value { font-size: 28px; font-weight: 600; color: var(--text); line-height: 1; }
  .stat-sub { font-size: 11px; color: var(--muted); margin-top: 5px; }
  .stat-accent { color: var(--accent2); }

  .top10-grid { display: flex; flex-direction: column; gap: 12px; }
  .prospect-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 20px 22px; transition: border-color .15s; }
  .prospect-card:hover { border-color: var(--border2); }
  .prospect-card.rank-1 { border-color: rgba(245,166,35,.3); background: linear-gradient(135deg, #141720 0%, #1a1608 100%); }
  .prospect-header { display: flex; align-items: flex-start; gap: 14px; margin-bottom: 14px; }
  .rank-badge { width: 32px; height: 32px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-family: var(--mono); font-size: 13px; font-weight: 500; flex-shrink: 0; background: rgba(255,255,255,.06); color: var(--muted); }
  .rank-badge.top { background: rgba(245,166,35,.15); color: var(--warn); }
  .prospect-name { font-size: 15px; font-weight: 500; color: var(--text); line-height: 1.3; }
  .prospect-meta { display: flex; gap: 8px; margin-top: 5px; flex-wrap: wrap; }
  .tag { font-family: var(--mono); font-size: 10px; padding: 2px 8px; border-radius: 4px; border: 1px solid var(--border2); color: var(--muted); }
  .tag.green { border-color: rgba(0,200,150,.25); color: var(--accent2); background: rgba(0,200,150,.05); }
  .tag.blue  { border-color: rgba(61,111,255,.25); color: var(--accent); background: rgba(61,111,255,.05); }
  .tag.warn  { border-color: rgba(245,166,35,.3); color: var(--warn); background: rgba(245,166,35,.06); }
  .score-bar-wrap { margin-left: auto; text-align: right; flex-shrink: 0; }
  .score-num { font-family: var(--mono); font-size: 20px; font-weight: 500; color: var(--text); }
  .score-label { font-size: 10px; color: var(--muted); }
  .reasons { display: flex; flex-direction: column; gap: 5px; margin-bottom: 14px; }
  .reason { font-size: 12px; color: var(--muted); line-height: 1.5; padding-left: 12px; border-left: 2px solid var(--border2); }
  .action-box { background: rgba(0,200,150,.05); border: 1px solid rgba(0,200,150,.15); border-radius: 6px; padding: 10px 14px; font-size: 12px; color: var(--accent2); }
  .action-label { font-family: var(--mono); font-size: 9px; letter-spacing: .1em; text-transform: uppercase; color: rgba(0,200,150,.5); margin-bottom: 3px; }

  .table-wrap { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
  .tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  .tbl thead th { background: rgba(255,255,255,.03); font-family: var(--mono); font-size: 10px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); padding: 12px 16px; text-align: left; border-bottom: 1px solid var(--border); font-weight: 400; }
  .tbl tbody td { padding: 11px 16px; border-bottom: 1px solid var(--border); color: var(--text); vertical-align: middle; }
  .tbl tbody tr:last-child td { border-bottom: none; }
  .tbl tbody tr:hover td { background: rgba(255,255,255,.02); }
  .repeat-pip { display: inline-flex; gap: 3px; }
  .pip { width: 6px; height: 6px; border-radius: 2px; background: var(--border2); }
  .pip.filled { background: var(--accent); }
  .pip.hot { background: var(--warn); }

  .sources-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }
  .source-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 20px 22px; }
  .source-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
  .source-name { font-size: 14px; font-weight: 500; }
  .source-url { font-family: var(--mono); font-size: 10px; color: var(--muted); margin-top: 3px; }
  .source-folder { font-family: var(--mono); font-size: 9px; color: var(--muted); margin-top: 2px; opacity: 0.6; }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; margin-top: 4px; }
  .status-dot.ok      { background: var(--accent2); box-shadow: 0 0 6px var(--accent2); }
  .status-dot.missing { background: var(--muted); }
  .status-dot.running { background: var(--warn); animation: pulse 1s infinite; }
  .status-dot.error   { background: var(--danger); }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
  .source-meta { font-size: 12px; color: var(--muted); margin-bottom: 14px; line-height: 1.6; }
  .source-footer { display: flex; justify-content: space-between; align-items: center; }
  .last-scraped { font-family: var(--mono); font-size: 10px; color: var(--muted); }
  .scrape-btn { background: rgba(61,111,255,.1); border: 1px solid rgba(61,111,255,.25); color: var(--accent); font-family: var(--sans); font-size: 11px; padding: 7px 14px; border-radius: 6px; cursor: pointer; transition: all .15s; }
  .scrape-btn:hover:not(:disabled) { background: rgba(61,111,255,.2); }
  .scrape-btn:disabled { opacity: .4; cursor: not-allowed; }
  .scrape-log { margin-top: 10px; font-family: var(--mono); font-size: 10px; color: var(--muted); background: rgba(0,0,0,.3); border-radius: 5px; padding: 8px 10px; min-height: 28px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  /* Run history */
  .runs-grid { display: flex; flex-direction: column; gap: 8px; }
  .run-row { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; display: flex; align-items: center; gap: 16px; }
  .run-name { font-family: var(--mono); font-size: 12px; color: var(--text); flex: 1; }
  .run-files { display: flex; gap: 6px; flex-wrap: wrap; }
  .run-file { font-family: var(--mono); font-size: 10px; padding: 2px 8px; border-radius: 4px; border: 1px solid var(--border2); color: var(--muted); }

  .section-title { font-family: var(--mono); font-size: 10px; letter-spacing: .1em; text-transform: uppercase; color: var(--muted); margin-bottom: 14px; }
  .loading { color: var(--muted); font-family: var(--mono); font-size: 12px; padding: 40px; text-align: center; }
</style>
</head>
<body>
<div class="shell">

  <!-- Sidebar -->
  <aside class="sidebar">
    <div class="logo">
      <div class="logo-tag">Kongu Corridor</div>
      <div class="logo-title">Signal Intelligence</div>
    </div>
    <nav class="nav">
      <div class="nav-item active" onclick="showPage('recommendations', this)">
        <div class="nav-dot"></div> Top 10 Prospects
      </div>
      <div class="nav-item" onclick="showPage('pipeline', this)">
        <div class="nav-dot"></div> Full Pipeline
      </div>
      <div class="nav-item" onclick="showPage('sources', this)">
        <div class="nav-dot"></div> Data Sources
      </div>
      <div class="nav-item" onclick="showPage('history', this)">
        <div class="nav-dot"></div> Run History
      </div>
    </nav>
    <div class="sidebar-bottom">
      <button class="refresh-btn" onclick="loadData()">↺ Refresh Data</button>
    </div>
  </aside>

  <!-- Main -->
  <main class="main">

    <!-- Stats row (always visible) -->
    <div class="stats-row" id="stats-row">
      <div class="loading" style="grid-column:1/-1">Loading...</div>
    </div>

    <!-- Page: Recommendations -->
    <div class="page active" id="page-recommendations">
      <div class="page-header">
        <div class="page-label">TNPCB · CTE Signal</div>
        <div class="page-title">Top 10 Prospects</div>
        <div class="page-sub">Ranked by expansion signal strength, recency, and manufacturing fit</div>
      </div>
      <div class="top10-grid" id="top10-container">
        <div class="loading">Loading prospects...</div>
      </div>
    </div>

    <!-- Page: Pipeline -->
    <div class="page" id="page-pipeline">
      <div class="page-header">
        <div class="page-label">TNPCB · CTE Signal</div>
        <div class="page-title">Full CTE Pipeline</div>
        <div class="page-sub">All manufacturing companies with active Consent to Establish — sorted by recency</div>
      </div>
      <div class="table-wrap">
        <table class="tbl">
          <thead>
            <tr>
              <th>#</th><th>Company</th><th>District</th>
              <th>Filed</th><th>Multi-plant</th><th>Type</th>
            </tr>
          </thead>
          <tbody id="pipeline-tbody">
            <tr><td colspan="6" class="loading">Loading...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Page: Sources -->
    <div class="page" id="page-sources">
      <div class="page-header">
        <div class="page-label">Automation</div>
        <div class="page-title">Data Sources</div>
        <div class="page-sub">Each run creates a timestamped folder in results/</div>
      </div>
      <div class="sources-grid" id="sources-container">
        <div class="loading">Loading...</div>
      </div>
    </div>

    <!-- Page: Run History -->
    <div class="page" id="page-history">
      <div class="page-header">
        <div class="page-label">Archive</div>
        <div class="page-title">Run History</div>
        <div class="page-sub">All past scrape runs stored in results/</div>
      </div>
      <div class="runs-grid" id="runs-container">
        <div class="loading">Loading...</div>
      </div>
    </div>

  </main>
</div>

<script>
const SOURCES_META = {
  tnpcb: {
    name: "TNPCB Consent Pipeline",
    url:  "ocmms.tn.gov.in",
    desc: "Consent to Establish (CTE) + Consent to Operate (CTO) filings for Kongu districts. Highest-lead-time signal — 9 to 18 months before space search."
  },
  udyam: {
    name: "Udyam MSME Registrations",
    url:  "udyamregistration.gov.in",
    desc: "Manufacturing companies registered by NIC code across Coimbatore, Tirupur and Erode. Cluster formation and sector growth signal."
  },
  ppa: {
    name: "TN Online PPA Plans",
    url:  "onlineppa.tn.gov.in",
    desc: "Industrial building plan approvals from DTCP, Rural Panchayat, Town Panchayat. Speculative shed under construction = motivated landlord."
  },
  dgcis: {
    name: "DGCIS Trade Data (ICD Irugur)",
    url:  "ftddp.dgciskol.gov.in",
    desc: "Import and export shipments through ICD Irugur (CBE). Machinery imports = confirmed capex. Export spike = urgent capacity need."
  },
  ccmc: {
    name: "CCMC Building Approvals",
    url:  "onlineppa.tn.gov.in",
    desc: "Corporation-level industrial building plan approvals. Speculative industrial shed = landlord without tenant = motivated counterparty."
  },
};

let pollTimers = {};
let statsData  = {};

function showPage(name, el) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-' + name).classList.add('active');
  if (el) el.classList.add('active');
  if (name === 'history') loadRuns();
}

async function loadData() {
  const res  = await fetch('/api/summary');
  const data = await res.json();
  statsData  = data.stats;
  renderStats(data.stats);
  renderTop10(data.top10);
  renderPipeline(data.pipeline);
  renderSources(data.stats);
}

async function loadRuns() {
  const res  = await fetch('/api/runs');
  const runs = await res.json();
  renderRuns(runs);
}

function renderStats(s) {
  document.getElementById('stats-row').innerHTML = `
    <div class="stat-card">
      <div class="stat-label">TNPCB Records</div>
      <div class="stat-value">${s.tnpcb_total.toLocaleString()}</div>
      <div class="stat-sub">CTE + CTO across Kongu</div>
    </div>
    <div class="stat-card">
      <div class="stat-value stat-accent">${s.tnpcb_cte}</div>
      <div class="stat-label" style="margin-top:4px">Consent to Establish</div>
      <div class="stat-sub"><span style="color:var(--warn)">${s.tnpcb_recent}</span> in last 90 days</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Udyam Companies</div>
      <div class="stat-value">${s.udyam_total.toLocaleString()}</div>
      <div class="stat-sub">Manufacturing registrations</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Active Sources</div>
      <div class="stat-value">${Object.values(s.sources).filter(v=>v==='ok').length}<span style="font-size:16px;color:var(--muted)">/${Object.keys(s.sources).length}</span></div>
      <div class="stat-sub">Data sources loaded</div>
    </div>
  `;
}

function renderTop10(list) {
  if (!list.length) {
    document.getElementById('top10-container').innerHTML = '<div class="loading">No data — run the TNPCB scraper first.</div>';
    return;
  }
  document.getElementById('top10-container').innerHTML = list.map(p => `
    <div class="prospect-card ${p.rank===1?'rank-1':''}">
      <div class="prospect-header">
        <div class="rank-badge ${p.rank<=3?'top':''}">
          ${p.rank <= 3 ? ['🥇','🥈','🥉'][p.rank-1] : '#' + p.rank}
        </div>
        <div style="flex:1">
          <div class="prospect-name">${p.name}</div>
          <div class="prospect-meta">
            <span class="tag blue">${p.district}</span>
            <span class="tag green">${p.signal}</span>
            <span class="tag">${p.date}</span>
            ${p.repeat > 1 ? `<span class="tag warn">${p.repeat}× filings</span>` : ''}
            <span class="tag">${p.lead_time} lead</span>
          </div>
        </div>
        <div class="score-bar-wrap">
          <div class="score-num">${p.score}</div>
          <div class="score-label">score</div>
        </div>
      </div>
      <div class="reasons">
        ${p.reasons.map(r => `<div class="reason">${r}</div>`).join('')}
      </div>
      <div class="action-box">
        <div class="action-label">Action</div>
        ${p.action}
      </div>
    </div>
  `).join('');
}

function renderPipeline(rows) {
  if (!rows.length) {
    document.getElementById('pipeline-tbody').innerHTML = '<tr><td colspan="6" class="loading">No data — run TNPCB scraper first.</td></tr>';
    return;
  }
  document.getElementById('pipeline-tbody').innerHTML = rows.map((r, i) => {
    const pips = Array.from({length: Math.min(r.repeat, 6)}, (_, j) =>
      `<div class="pip ${r.repeat >= 6 ? 'hot' : 'filled'}"></div>`
    ).join('');
    return `
      <tr>
        <td style="color:var(--muted);font-family:var(--mono);font-size:11px">${i+1}</td>
        <td style="font-weight:500">${r.name}</td>
        <td><span class="tag blue" style="font-size:10px">${r.district}</span></td>
        <td style="font-family:var(--mono);font-size:11px;color:var(--muted)">${r.date}</td>
        <td><div class="repeat-pip">${pips}</div></td>
        <td><span class="tag green" style="font-size:10px">${r.type}</span></td>
      </tr>
    `;
  }).join('');
}

function renderSources(stats) {
  const container = document.getElementById('sources-container');
  container.innerHTML = Object.entries(SOURCES_META).map(([key, meta]) => {
    const status     = stats.sources[key] || 'missing';
    const lastScrape = stats.last_scraped[key] || 'Never';
    const folder     = stats.run_folders[key] || '';
    return `
      <div class="source-card" id="source-card-${key}">
        <div class="source-header">
          <div>
            <div class="source-name">${meta.name}</div>
            <div class="source-url">${meta.url}</div>
            ${folder ? `<div class="source-folder">📁 results/${folder}</div>` : ''}
          </div>
          <div class="status-dot ${status}" id="dot-${key}"></div>
        </div>
        <div class="source-meta">${meta.desc}</div>
        <div class="source-footer">
          <div class="last-scraped">Last run: ${lastScrape}</div>
          <button class="scrape-btn" id="btn-${key}" onclick="runScraper('${key}')">▶ Run Scraper</button>
        </div>
        <div class="scrape-log" id="log-${key}" style="display:none"></div>
      </div>
    `;
  }).join('');
}

function renderRuns(runs) {
  const container = document.getElementById('runs-container');
  if (!runs.length) {
    container.innerHTML = '<div class="loading">No runs yet. Click Run Scraper on a source to start.</div>';
    return;
  }
  container.innerHTML = runs.map(r => `
    <div class="run-row">
      <div class="run-name">📁 ${r.folder}</div>
      <div class="run-files">
        ${r.files.map(f => `<span class="run-file">${f}</span>`).join('')}
        ${r.files.length === 0 ? '<span class="run-file" style="opacity:.4">empty</span>' : ''}
      </div>
    </div>
  `).join('');
}

async function runScraper(source) {
  const btn = document.getElementById('btn-' + source);
  const dot = document.getElementById('dot-' + source);
  const log = document.getElementById('log-' + source);

  btn.disabled = true;
  btn.textContent = '⏳ Running...';
  dot.className = 'status-dot running';
  log.style.display = 'block';
  log.textContent = 'Starting scraper...';

  await fetch('/api/scrape/' + source, { method: 'POST' });

  clearInterval(pollTimers[source]);
  pollTimers[source] = setInterval(async () => {
    const res  = await fetch('/api/scrape_status/' + source);
    const data = await res.json();
    log.textContent = data.log || '...';

    if (data.status === 'done') {
      clearInterval(pollTimers[source]);
      btn.disabled = false;
      btn.textContent = '▶ Run Scraper';
      dot.className = 'status-dot ok';
      log.textContent = '✅ Done — click Refresh Data to reload.';
      loadData(); // auto-refresh stats + folder name
    } else if (data.status === 'error') {
      clearInterval(pollTimers[source]);
      btn.disabled = false;
      btn.textContent = '▶ Run Scraper';
      dot.className = 'status-dot error';
    }
  }, 1500);
}

// Init
loadData();
</script>
</body>
</html>
"""

# ── Launch ─────────────────────────────────────────────────────────────────────
def open_browser():
    import time
    time.sleep(1.2)
    webbrowser.open("http://localhost:5000")


if __name__ == "__main__":
    print("=" * 55)
    print("  Kongu Signal Intelligence Dashboard")
    print("=" * 55)
    print(f"  Data dir : {RESULTS_DIR}")
    print(f"  URL      : http://localhost:5000")
    print("  Press Ctrl+C to stop")
    print("=" * 55)

    # Show current state from latest.json
    all_latest = get_all_latest()
    for key, path in all_latest.items():
        if path:
            print(f"  {key:<8} ✅  {path.relative_to(BASE_DIR)}")
        else:
            print(f"  {key:<8} ⚠️   no data yet")
    print()

    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host="127.0.0.1", port=5000, debug=False)