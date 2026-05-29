"""
Kongu Signal Intelligence Dashboard — Streamlit Version
========================================================
Deploy on Streamlit Cloud:
  1. Push this file + your results/ CSVs to GitHub
  2. Deploy at share.streamlit.io → select this file as main file

Local run:
    pip install streamlit pandas
    streamlit run streamlit_app.py
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

# ── Page config ───────────────────────────────────────────────────
st.set_page_config(
    page_title="Kongu Signal Intelligence",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS (dark theme matching original) ─────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Sora:wght@300;400;500;600&display=swap');

html, body, [class*="css"] {
    font-family: 'Sora', sans-serif;
    background-color: #0d0f12;
    color: #e8eaf0;
}
.stApp { background-color: #0d0f12; }

/* Stat cards */
.stat-card {
    background: #141720;
    border: 1px solid #1e2330;
    border-radius: 10px;
    padding: 18px 20px;
    margin-bottom: 8px;
}
.stat-label {
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    color: #6b7490;
    letter-spacing: .08em;
    text-transform: uppercase;
    margin-bottom: 6px;
}
.stat-value {
    font-size: 28px;
    font-weight: 600;
    color: #e8eaf0;
    line-height: 1;
}
.stat-sub { font-size: 11px; color: #6b7490; margin-top: 5px; }
.stat-accent { color: #00c896 !important; }

/* Prospect cards */
.prospect-card {
    background: #141720;
    border: 1px solid #1e2330;
    border-radius: 10px;
    padding: 20px 22px;
    margin-bottom: 12px;
}
.prospect-card.rank-1 {
    border-color: rgba(245,166,35,.3);
    background: linear-gradient(135deg, #141720 0%, #1a1608 100%);
}
.prospect-name { font-size: 15px; font-weight: 500; margin-bottom: 6px; }
.tag {
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 4px;
    border: 1px solid #2a3045;
    color: #6b7490;
    margin-right: 4px;
    display: inline-block;
}
.tag-blue  { border-color: rgba(61,111,255,.3); color: #3d6fff; background: rgba(61,111,255,.06); }
.tag-green { border-color: rgba(0,200,150,.3);  color: #00c896; background: rgba(0,200,150,.06); }
.tag-warn  { border-color: rgba(245,166,35,.3); color: #f5a623; background: rgba(245,166,35,.06); }
.reason {
    font-size: 12px;
    color: #6b7490;
    line-height: 1.5;
    padding-left: 12px;
    border-left: 2px solid #2a3045;
    margin: 4px 0;
}
.action-box {
    background: rgba(0,200,150,.05);
    border: 1px solid rgba(0,200,150,.15);
    border-radius: 6px;
    padding: 10px 14px;
    font-size: 12px;
    color: #00c896;
    margin-top: 12px;
}
.score-badge {
    font-family: 'DM Mono', monospace;
    font-size: 22px;
    font-weight: 500;
    color: #e8eaf0;
    float: right;
}

/* Source cards */
.source-card {
    background: #141720;
    border: 1px solid #1e2330;
    border-radius: 10px;
    padding: 20px 22px;
    margin-bottom: 12px;
}
.source-name { font-size: 14px; font-weight: 500; }
.source-url  { font-family: 'DM Mono', monospace; font-size: 10px; color: #6b7490; margin-top: 3px; }
.source-meta { font-size: 12px; color: #6b7490; margin: 10px 0; line-height: 1.6; }
.dot-ok      { display:inline-block; width:8px; height:8px; border-radius:50%; background:#00c896; margin-right:6px; }
.dot-missing { display:inline-block; width:8px; height:8px; border-radius:50%; background:#6b7490; margin-right:6px; }

/* Sidebar */
section[data-testid="stSidebar"] {
    background-color: #141720 !important;
    border-right: 1px solid #1e2330;
}
section[data-testid="stSidebar"] * { color: #e8eaf0 !important; }

/* Dataframe */
.stDataFrame { background: #141720; }
</style>
""", unsafe_allow_html=True)

# ── Paths ──────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
RESULTS_DIR = BASE_DIR / "results"
LATEST_FILE = RESULTS_DIR / "latest.json"

NON_MFG_KEYWORDS = [
    "REALTY", "BUILDERS", "SHELTERS", "PROMOTERS", "INFRA MAT",
    "BLUE METALS", "M-SAND", "M SAND", "MSAND", "HATCHERIES",
    "CREMATORIUM", "MUNICIPALITY", "PANCHAYAT", "ACADEMY",
    "INSTITUTE", "TRUST", "DEVELOPERS LLP", "STONE CRUSHER",
    "CRUSHER", "SEWAGE", "BRICKS",
]

SOURCE_KEYS = ["tnpcb", "udyam", "ppa", "dgcis", "ccmc"]

SOURCES_META = {
    "tnpcb": {
        "name": "TNPCB Consent Pipeline",
        "url":  "ocmms.tn.gov.in",
        "desc": "Consent to Establish (CTE) + Consent to Operate (CTO) filings for Kongu districts. Highest-lead-time signal — 9 to 18 months before space search.",
    },
    "udyam": {
        "name": "Udyam MSME Registrations",
        "url":  "udyamregistration.gov.in",
        "desc": "Manufacturing companies registered by NIC code across Coimbatore, Tirupur and Erode. Cluster formation and sector growth signal.",
    },
    "ppa": {
        "name": "TN Online PPA Plans",
        "url":  "onlineppa.tn.gov.in",
        "desc": "Industrial building plan approvals from DTCP, Rural Panchayat, Town Panchayat. Speculative shed under construction = motivated landlord.",
    },
    "dgcis": {
        "name": "DGCIS Trade Data (ICD Irugur)",
        "url":  "ftddp.dgciskol.gov.in",
        "desc": "Import and export shipments through ICD Irugur (CBE). Machinery imports = confirmed capex. Export spike = urgent capacity need.",
    },
    "ccmc": {
        "name": "CCMC Building Approvals",
        "url":  "onlineppa.tn.gov.in",
        "desc": "Corporation-level industrial building plan approvals. Speculative industrial shed = landlord without tenant = motivated counterparty.",
    },
}


# ── Data helpers ──────────────────────────────────────────────────
@st.cache_data(ttl=300)
def get_latest_csv(source_key: str):
    if not LATEST_FILE.exists():
        return None
    try:
        latest = json.loads(LATEST_FILE.read_text())
        rel = latest.get(source_key)
        if not rel:
            return None
        p = RESULTS_DIR / rel
        return p if p.exists() else None
    except Exception:
        return None


@st.cache_data(ttl=300)
def load_tnpcb():
    f = get_latest_csv("tnpcb")
    if not f:
        return pd.DataFrame()
    df = pd.read_csv(f)
    df["app_date"] = pd.to_datetime(df["application_date"], dayfirst=True, errors="coerce")
    return df


@st.cache_data(ttl=300)
def load_udyam():
    f = get_latest_csv("udyam")
    if not f:
        return pd.DataFrame()
    df = pd.read_csv(f)
    df = df[~df["company_name"].astype(str).str.match(r"^\d+$")]
    return df


def is_manufacturing(name):
    n = str(name).upper()
    return not any(kw in n for kw in NON_MFG_KEYWORDS)


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

    tnpcb_recent = 0
    if not df_t.empty:
        cutoff = datetime.now() - timedelta(days=90)
        cte = df_t[df_t["application_type"] == "CTE"]
        cte_dates = pd.to_datetime(cte["application_date"], dayfirst=True, errors="coerce")
        tnpcb_recent = int((cte_dates >= cutoff).sum())

    sources_ok = sum(1 for k in SOURCE_KEYS if get_latest_csv(k) is not None)

    return {
        "tnpcb_total":  len(df_t),
        "tnpcb_cte":    int((df_t["application_type"] == "CTE").sum()) if not df_t.empty else 0,
        "tnpcb_recent": tnpcb_recent,
        "udyam_total":  len(df_u),
        "sources_ok":   sources_ok,
        "sources_total": len(SOURCE_KEYS),
        "regions":       df_t["region"].value_counts().to_dict() if not df_t.empty else {},
        "industries":    df_u["industry"].value_counts().head(5).to_dict() if not df_u.empty else {},
    }


def compute_pipeline():
    df = load_tnpcb()
    if df.empty:
        return pd.DataFrame()
    cte = df[df["application_type"] == "CTE"].copy()
    cte = cte[cte["company_name"].apply(is_manufacturing)]
    cte = cte.sort_values("app_date", ascending=False).drop_duplicates("company_name")
    repeat = df[df["application_type"] == "CTE"]["company_name"].value_counts().to_dict()
    cte["filings"] = cte["company_name"].map(repeat).fillna(1).astype(int)
    return cte[["company_name", "district", "application_date", "filings", "application_type"]].head(50).rename(columns={
        "company_name": "Company",
        "district": "District",
        "application_date": "Filed",
        "filings": "Filings",
        "application_type": "Type",
    })


# ── Sidebar ───────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding-bottom:20px; border-bottom:1px solid #1e2330; margin-bottom:20px">
        <div style="font-family:'DM Mono',monospace; font-size:9px; color:#6b7490; letter-spacing:.12em; text-transform:uppercase; margin-bottom:4px">Kongu Corridor</div>
        <div style="font-size:16px; font-weight:600">Signal Intelligence</div>
    </div>
    """, unsafe_allow_html=True)

    page = st.radio(
        "Navigate",
        ["⚡ Top 10 Prospects", "📋 Full Pipeline", "🔌 Data Sources"],
        label_visibility="collapsed",
    )

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("↺ Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("""
    <div style="font-family:'DM Mono',monospace; font-size:9px; color:#6b7490; line-height:1.8">
    Run scrapers locally on your Mac,<br>
    push CSVs to GitHub → data updates here.
    </div>
    """, unsafe_allow_html=True)


# ── Stats row (always visible) ────────────────────────────────────
stats = compute_stats()

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(f"""<div class="stat-card">
        <div class="stat-label">TNPCB Records</div>
        <div class="stat-value">{stats['tnpcb_total']:,}</div>
        <div class="stat-sub">CTE + CTO across Kongu</div>
    </div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""<div class="stat-card">
        <div class="stat-label">Consent to Establish</div>
        <div class="stat-value stat-accent">{stats['tnpcb_cte']}</div>
        <div class="stat-sub"><span style="color:#f5a623">{stats['tnpcb_recent']}</span> in last 90 days</div>
    </div>""", unsafe_allow_html=True)
with c3:
    st.markdown(f"""<div class="stat-card">
        <div class="stat-label">Udyam Companies</div>
        <div class="stat-value">{stats['udyam_total']:,}</div>
        <div class="stat-sub">Manufacturing registrations</div>
    </div>""", unsafe_allow_html=True)
with c4:
    st.markdown(f"""<div class="stat-card">
        <div class="stat-label">Active Sources</div>
        <div class="stat-value">{stats['sources_ok']}<span style="font-size:16px;color:#6b7490">/{stats['sources_total']}</span></div>
        <div class="stat-sub">Data sources loaded</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Pages ─────────────────────────────────────────────────────────

if page == "⚡ Top 10 Prospects":
    st.markdown("""
    <div style="margin-bottom:24px">
        <div style="font-family:'DM Mono',monospace; font-size:10px; color:#6b7490; letter-spacing:.1em; text-transform:uppercase; margin-bottom:4px">TNPCB · CTE Signal</div>
        <div style="font-size:22px; font-weight:600">Top 10 Prospects</div>
        <div style="font-size:13px; color:#6b7490; margin-top:4px">Ranked by expansion signal strength, recency, and manufacturing fit</div>
    </div>
    """, unsafe_allow_html=True)

    top10 = compute_top10()
    if not top10:
        st.markdown('<div style="color:#6b7490; font-family:\'DM Mono\',monospace; padding:40px; text-align:center">No data — run the TNPCB scraper first, then push results/ to GitHub.</div>', unsafe_allow_html=True)
    else:
        for p in top10:
            rank_emoji = ["🥇", "🥈", "🥉"][p["rank"] - 1] if p["rank"] <= 3 else f"#{p['rank']}"
            card_class = "prospect-card rank-1" if p["rank"] == 1 else "prospect-card"
            repeat_tag = f'<span class="tag tag-warn">{p["repeat"]}× filings</span>' if p["repeat"] > 1 else ""
            reasons_html = "".join(f'<div class="reason">{r}</div>' for r in p["reasons"])

            st.markdown(f"""
            <div class="{card_class}">
                <div style="display:flex; justify-content:space-between; align-items:flex-start">
                    <div style="flex:1">
                        <span style="font-size:18px; margin-right:10px">{rank_emoji}</span>
                        <span class="prospect-name">{p['name']}</span>
                        <div style="margin-top:6px">
                            <span class="tag tag-blue">{p['district']}</span>
                            <span class="tag tag-green">{p['signal']}</span>
                            <span class="tag">{p['date']}</span>
                            {repeat_tag}
                            <span class="tag">{p['lead_time']} lead</span>
                        </div>
                    </div>
                    <div style="text-align:right; flex-shrink:0; margin-left:16px">
                        <div style="font-family:'DM Mono',monospace; font-size:22px; font-weight:500">{p['score']}</div>
                        <div style="font-size:10px; color:#6b7490">score</div>
                    </div>
                </div>
                <div style="margin:14px 0">{reasons_html}</div>
                <div class="action-box">
                    <div style="font-family:'DM Mono',monospace; font-size:9px; letter-spacing:.1em; text-transform:uppercase; color:rgba(0,200,150,.5); margin-bottom:3px">Action</div>
                    {p['action']}
                </div>
            </div>
            """, unsafe_allow_html=True)


elif page == "📋 Full Pipeline":
    st.markdown("""
    <div style="margin-bottom:24px">
        <div style="font-family:'DM Mono',monospace; font-size:10px; color:#6b7490; letter-spacing:.1em; text-transform:uppercase; margin-bottom:4px">TNPCB · CTE Signal</div>
        <div style="font-size:22px; font-weight:600">Full CTE Pipeline</div>
        <div style="font-size:13px; color:#6b7490; margin-top:4px">All manufacturing companies with active Consent to Establish — sorted by recency</div>
    </div>
    """, unsafe_allow_html=True)

    pipeline_df = compute_pipeline()
    if pipeline_df.empty:
        st.markdown('<div style="color:#6b7490; font-family:\'DM Mono\',monospace; padding:40px; text-align:center">No data — run TNPCB scraper first.</div>', unsafe_allow_html=True)
    else:
        st.dataframe(
            pipeline_df,
            use_container_width=True,
            hide_index=True,
            height=600,
        )


elif page == "🔌 Data Sources":
    st.markdown("""
    <div style="margin-bottom:24px">
        <div style="font-family:'DM Mono',monospace; font-size:10px; color:#6b7490; letter-spacing:.1em; text-transform:uppercase; margin-bottom:4px">Data</div>
        <div style="font-size:22px; font-weight:600">Data Sources</div>
        <div style="font-size:13px; color:#6b7490; margin-top:4px">Run scrapers locally → push results/ to GitHub → data updates here</div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    items = list(SOURCES_META.items())

    for i, (key, meta) in enumerate(items):
        csv_path = get_latest_csv(key)
        status   = "ok" if csv_path else "missing"
        dot      = '<span class="dot-ok"></span>' if status == "ok" else '<span class="dot-missing"></span>'

        if csv_path:
            mtime = datetime.fromtimestamp(csv_path.stat().st_mtime)
            last_run = mtime.strftime("%d %b %Y, %H:%M")
            folder = csv_path.parent.name
        else:
            last_run = "Never"
            folder   = ""

        folder_line = f'<div style="font-family:\'DM Mono\',monospace; font-size:9px; color:#6b7490; opacity:.6; margin-top:2px">📁 results/{folder}</div>' if folder else ""

        card_html = f"""
        <div class="source-card">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:10px">
                <div>
                    <div class="source-name">{dot}{meta['name']}</div>
                    <div class="source-url">{meta['url']}</div>
                    {folder_line}
                </div>
            </div>
            <div class="source-meta">{meta['desc']}</div>
            <div style="font-family:'DM Mono',monospace; font-size:10px; color:#6b7490">Last run: {last_run}</div>
        </div>
        """

        if i % 2 == 0:
            with col1:
                st.markdown(card_html, unsafe_allow_html=True)
        else:
            with col2:
                st.markdown(card_html, unsafe_allow_html=True)

    st.markdown("""
    <div style="background:#141720; border:1px solid #1e2330; border-radius:10px; padding:20px; margin-top:8px">
        <div style="font-family:'DM Mono',monospace; font-size:10px; color:#6b7490; letter-spacing:.1em; text-transform:uppercase; margin-bottom:10px">How to update data</div>
        <div style="font-size:13px; color:#6b7490; line-height:1.8">
            1. Run scrapers on your Mac: <code style="background:#0d0f12; padding:2px 6px; border-radius:3px; font-family:'DM Mono',monospace">python tnpcb_scraper.py</code><br>
            2. Commit the new <code style="background:#0d0f12; padding:2px 6px; border-radius:3px; font-family:'DM Mono',monospace">results/</code> folder to GitHub<br>
            3. Streamlit auto-redeploys — click ↺ Refresh Data in sidebar
        </div>
    </div>
    """, unsafe_allow_html=True)
