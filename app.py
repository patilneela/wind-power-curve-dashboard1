import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from scipy.signal import savgol_filter
from datetime import timedelta
import os
import io

from reportlab.lib.pagesizes import landscape, A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

# =========================
# PAGE CONFIG
# =========================
st.set_page_config(layout="wide")

# =========================
# SIMPLE LOCK (single user)
# =========================
def login_gate():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        return

    st.title("Login Required")

    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")
        submitted = st.form_submit_button("Login")

    if submitted:
        cfg = st.secrets.get("auth", {})
        ok = (username == cfg.get("username")) and (password == cfg.get("password"))

        if ok:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Invalid username or password")

    st.stop()

login_gate()

if st.sidebar.button("Logout", key="logout_btn"):
    st.session_state.authenticated = False
    st.rerun()

# SAFE KALEIDO CHECK
try:
    import kaleido  # noqa: F401
    KALEIDO_AVAILABLE = True
except Exception:
    KALEIDO_AVAILABLE = False

# =========================
# PATHS (same folder as app)
# =========================
BASE_DIR = os.path.dirname(__file__)
REF_FILE_PATH = os.path.join(BASE_DIR, "reference.xlsx")
SITE_MASTER_XLSX = os.path.join(BASE_DIR, "site_master.xlsx")
SITE_MASTER_CSV = os.path.join(BASE_DIR, "site_master.csv")

BIN_SIZE = 0.5

# =========================
# HELPERS
# =========================
def get_site_master_path():
    if os.path.exists(SITE_MASTER_XLSX):
        return SITE_MASTER_XLSX
    if os.path.exists(SITE_MASTER_CSV):
        return SITE_MASTER_CSV
    return None

def compute_preset_range(preset: str, today_ts: pd.Timestamp):
    """
    Returns (start_day, end_day) as python dates, inclusive.
    Based on real "today".
    """
    today_date = today_ts.normalize().date()

    if preset == "Today":
        return today_date, today_date

    if preset == "This Week":
        monday = today_date - timedelta(days=today_ts.weekday())
        return monday, today_date

    if preset == "Last Week":
        this_monday = today_date - timedelta(days=today_ts.weekday())
        start = this_monday - timedelta(days=7)
        end = this_monday - timedelta(days=1)
        return start, end

    if preset == "This Month":
        start = today_date.replace(day=1)
        return start, today_date

    if preset == "Last Month":
        first_this_month = today_date.replace(day=1)
        last_month_end = first_this_month - timedelta(days=1)
        start = last_month_end.replace(day=1)
        return start, last_month_end

    return None

# =========================
# LOGO
# =========================
logo_path = os.path.join(BASE_DIR, "Envision.png")
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if os.path.exists(logo_path):
        st.image(logo_path, width=300)

# =========================
# TITLE
# =========================
st.title("Power Curve Analytics Report")

# =========================
# DEFAULT SITE CAPACITY (fallback)
# =========================
DEFAULT_SITE_CAPACITY = {
    site: 3.3 for site in [
        "CIP Hatalageri",
        "JSW Tuljapur",
        "Blupine Sagapara",
        "Kalavad GJ",
        "Kalavad_PH2",
        "AMP_Energy",
        "Wanki",
        "CleanMax Motadevaliya",
        "Ayana Amerli",
        "Mahadev PH1",
        "Blupine-I, Ambada-GJ",
        "ACME Shapar",
        "FP_Kudligi",
        "Sprng TN",
        "Otha Pithalpur-GJ",
        "AMGEPL,Kurnool AP",
        "ReNew1_Gadag",
        "partner Ottapidaum",
        "Cleanmax SANATHALI",
        "Cleanmax Babra",
        "RenfraEnergy Trichy",
        "RENEW-03 Sholapur",
        "Renew2 Chandwad",
        "ReNew-4 Patoda",
        "Clean max Jagalur",
        "Sembcorp Tuticorin",
        "Renew-4 Kudligi",
        "Renew Otha",
        "Cleanmax Honavad",
        "Blueleaf Agar",
        "JSW_Sandur",
        "India_Hero_Doni"
    ]
}

@st.cache_data
def load_site_capacity():
    capacity = dict(DEFAULT_SITE_CAPACITY)
    path = get_site_master_path()
    if path is None:
        return capacity

    try:
        if path.lower().endswith(".csv"):
            sm = pd.read_csv(path)
        else:
            sm = pd.read_excel(path)

        sm.columns = [c.strip() for c in sm.columns]

        site_col = None
        cap_col = None
        for c in sm.columns:
            if c.lower() in ["site", "site_name", "sitename", "plant", "project"]:
                site_col = c
            if c.lower() in ["capacity_mw", "capacity", "turbine_capacity_mw", "mw"]:
                cap_col = c

        if site_col is None or cap_col is None:
            st.warning("site_master file found but columns not recognized. Required: Site + Capacity_MW.")
            return capacity

        sm = sm[[site_col, cap_col]].dropna()
        sm[site_col] = sm[site_col].astype(str).str.strip()
        sm[cap_col] = pd.to_numeric(sm[cap_col], errors="coerce")
        sm = sm.dropna()

        for _, row in sm.iterrows():
            capacity[row[site_col]] = float(row[cap_col])

        return capacity

    except Exception as e:
        st.warning("Failed to read site_master. Using default site list.")
        st.code(str(e))
        return capacity

SITE_CAPACITY = load_site_capacity()

# =========================
# TABS
# =========================
tab_dashboard, tab_admin = st.tabs(["Dashboard", "Site Add-on / Admin"])

# ==========================================================
# TAB: ADMIN
# ==========================================================
with tab_admin:
    st.subheader("Site Add-on")
    st.divider()

    st.markdown("## 1) Reference Excel (reference.xlsx)")

    if os.path.exists(REF_FILE_PATH):
        st.success(f"Reference file found: `{os.path.basename(REF_FILE_PATH)}`")
    else:
        st.warning("Reference file missing. Upload a reference Excel to enable power curve reference comparison.")

    ref_upload = st.file_uploader(
        "Upload / Replace Reference Excel (.xlsx)",
        type=["xlsx"],
        key="ref_upload"
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Save / Replace Reference Excel", type="primary"):
            if ref_upload is None:
                st.error("Please choose an .xlsx file first.")
            else:
                with open(REF_FILE_PATH, "wb") as f:
                    f.write(ref_upload.getbuffer())
                st.success("Reference Excel saved/replaced.")
                st.cache_data.clear()
                st.rerun()

    with c2:
        if st.button("Delete Reference Excel"):
            if os.path.exists(REF_FILE_PATH):
                os.remove(REF_FILE_PATH)
                st.success("Reference Excel deleted.")
                st.cache_data.clear()
                st.rerun()
            else:
                st.info("No reference file to delete.")

    if os.path.exists(REF_FILE_PATH):
        with st.expander("Preview reference.xlsx (first 30 rows)"):
            try:
                tmp = pd.read_excel(REF_FILE_PATH, header=None)
                st.dataframe(tmp.head(30), use_container_width=True)
            except Exception as e:
                st.error("Unable to read reference.xlsx")
                st.code(str(e))

    st.divider()

    st.markdown("## 2) Site Master (site_master.xlsx / site_master.csv)")

    existing_sm = get_site_master_path()
    if existing_sm:
        st.success(f"Site Master found: `{os.path.basename(existing_sm)}`")
    else:
        st.info("No Site Master file found. Dashboard will use the hardcoded default site list.")

    sm_upload = st.file_uploader(
        "Upload / Replace Site Master (.xlsx or .csv)",
        type=["xlsx", "csv"],
        key="sm_upload"
    )

    c3, c4 = st.columns(2)
    with c3:
        if st.button("Save / Replace Site Master", type="primary"):
            if sm_upload is None:
                st.error("Please choose a .xlsx or .csv file first.")
            else:
                ext = os.path.splitext(sm_upload.name)[1].lower()
                if ext not in [".xlsx", ".csv"]:
                    st.error("Only .xlsx or .csv supported.")
                else:
                    target = os.path.join(BASE_DIR, f"site_master{ext}")

                    if target != SITE_MASTER_XLSX and os.path.exists(SITE_MASTER_XLSX):
                        os.remove(SITE_MASTER_XLSX)
                    if target != SITE_MASTER_CSV and os.path.exists(SITE_MASTER_CSV):
                        os.remove(SITE_MASTER_CSV)

                    with open(target, "wb") as f:
                        f.write(sm_upload.getbuffer())

                    st.success(f"Site Master saved as `{os.path.basename(target)}`")
                    st.cache_data.clear()
                    st.rerun()

    with c4:
        if st.button("Delete Site Master"):
            deleted = False
            if os.path.exists(SITE_MASTER_XLSX):
                os.remove(SITE_MASTER_XLSX)
                deleted = True
            if os.path.exists(SITE_MASTER_CSV):
                os.remove(SITE_MASTER_CSV)
                deleted = True

            if deleted:
                st.success("Site Master deleted.")
                st.cache_data.clear()
                st.rerun()
            else:
                st.info("No Site Master file to delete.")

    existing_sm = get_site_master_path()
    if existing_sm:
        with st.expander("Preview Site Master"):
            try:
                if existing_sm.endswith(".csv"):
                    sm_df = pd.read_csv(existing_sm)
                else:
                    sm_df = pd.read_excel(existing_sm)
                st.dataframe(sm_df.head(50), use_container_width=True)
            except Exception as e:
                st.error("Unable to read Site Master file.")
                st.code(str(e))

# ==========================================================
# TAB: DASHBOARD
# ==========================================================
with tab_dashboard:

    st.sidebar.subheader("Upload SCADA File")
    uploaded_file = st.sidebar.file_uploader("Upload SCADA CSV", type=["csv"], key="scada_upload")

    if uploaded_file is None:
        st.warning("Please upload SCADA file")
        st.stop()

    if not os.path.exists(REF_FILE_PATH):
        st.error("Reference Excel is missing. Upload `reference.xlsx` in the Admin tab.")
        st.stop()

    site = st.sidebar.selectbox("Select Site", list(SITE_CAPACITY.keys()), key="site_select")
    mode = st.sidebar.radio("Select View", ["Single Turbine", "Compare Turbines", "Show All Turbines"], key="mode_radio")

    # =========================
    # LOAD SCADA
    # =========================
    @st.cache_data(show_spinner=True)
    def load_scada(file):
        chunksize = 200000
        chunks = pd.read_csv(
            file,
            chunksize=chunksize,
            low_memory=False,
            engine="c"
        )
        df_local = pd.concat(chunks, ignore_index=True)
        df_local.columns = df_local.columns.str.strip()

        if "Name" not in df_local.columns:
            st.error("SCADA CSV must contain a 'Name' column for turbine identifier.")
            st.stop()

        wind_col = [c for c in df_local.columns if "wind" in c.lower()][0]
        power_col = [c for c in df_local.columns if "power" in c.lower() or "active" in c.lower()][0]
        time_col = [c for c in df_local.columns if "time" in c.lower()][0]
        pitch_col = [c for c in df_local.columns if "pitch" in c.lower()][0]

        df_local[time_col] = pd.to_datetime(df_local[time_col], errors="coerce")
        df_local[wind_col] = pd.to_numeric(df_local[wind_col], errors="coerce")
        df_local[power_col] = pd.to_numeric(df_local[power_col], errors="coerce")
        df_local[pitch_col] = pd.to_numeric(df_local[pitch_col], errors="coerce")

        df_local = df_local.dropna(subset=[wind_col, power_col, time_col, pitch_col])
        df_local["Name"] = df_local["Name"].astype(str).str.strip()

        return df_local, wind_col, power_col, time_col, pitch_col

    with st.spinner("Loading SCADA file..."):
        df, wind_col, power_col, time_col, pitch_col = load_scada(uploaded_file)

    if df.empty:
        st.warning("SCADA file has no valid rows after parsing.")
        st.stop()

    # =========================
    # DATE FILTER (Single dropdown + Manual calendar)
    # =========================
    st.sidebar.markdown("### Date Range")

    max_ts = df[time_col].max()
    base_date = max_ts.normalize().date() if pd.notna(max_ts) else pd.Timestamp.today().date()

    DEFAULT_START = base_date - timedelta(days=15)
    DEFAULT_END = base_date

    if "manual_start_date" not in st.session_state:
        st.session_state.manual_start_date = DEFAULT_START
    if "manual_end_date" not in st.session_state:
        st.session_state.manual_end_date = DEFAULT_END

    date_option = st.sidebar.selectbox(
        "Date Option",
        ["Clear", "Today", "This Week", "This Month", "Last Week", "Last Month", "Manual (Calendar)"],
        key="date_option"
    )

    if date_option == "Manual (Calendar)":
        st.sidebar.markdown("#### Manual Selection")
        start_day = st.sidebar.date_input("Start Date", value=st.session_state.manual_start_date, key="manual_start_date")
        end_day = st.sidebar.date_input("End Date", value=st.session_state.manual_end_date, key="manual_end_date")

    elif date_option == "Clear":
        st.session_state.manual_start_date = DEFAULT_START
        st.session_state.manual_end_date = DEFAULT_END
        start_day = DEFAULT_START
        end_day = DEFAULT_END

    else:
        rng = compute_preset_range(date_option, pd.Timestamp.today())
        if rng is None:
            start_day, end_day = DEFAULT_START, DEFAULT_END
        else:
            start_day, end_day = rng

    # Day-wise filter (ignore time)
    df["_date_only"] = df[time_col].dt.date
    df = df[(df["_date_only"] >= start_day) & (df["_date_only"] <= end_day)]
    df = df.drop(columns=["_date_only"])

    st.sidebar.caption(f"Applied Range: {start_day} → {end_day}")

    if df.empty:
        st.warning("No SCADA data available for the selected date range.")
        st.stop()

    # =========================
    # HEADER
    # =========================
    num_turbines = df["Name"].nunique()
    capacity_per_turbine = SITE_CAPACITY.get(site, 3.3)
    total_capacity = num_turbines * capacity_per_turbine

    st.subheader(
        f"{site} | "
        f"{num_turbines} Turbines | "
        f"{capacity_per_turbine} MW Each | "
        f"Total: {round(total_capacity, 2)} MW"
    )
    st.markdown(f"Date Range: {start_day} → {end_day}")

    # =========================
    # LOAD REFERENCE
    # =========================
    @st.cache_data
    def load_reference(site_name):
        ref_raw = pd.read_excel(REF_FILE_PATH, header=None)

        for r in range(ref_raw.shape[0]):
            for c in range(ref_raw.shape[1]):
                cell = str(ref_raw.iloc[r, c])
                if site_name.lower() in cell.lower():
                    ref = ref_raw.iloc[r + 2:r + 60, [c - 1, c + 3]].copy()
                    ref.columns = ["WindSpeed", "RefPower"]
                    ref = ref.dropna()

                    ref["WindSpeed"] = pd.to_numeric(ref["WindSpeed"], errors="coerce")
                    ref["RefPower"] = pd.to_numeric(ref["RefPower"], errors="coerce")
                    ref = ref.dropna()

                    wind_bins = np.arange(4, 15, BIN_SIZE)
                    ref_interp = np.interp(wind_bins, ref["WindSpeed"], ref["RefPower"])

                    return pd.DataFrame({"WindBin": wind_bins, "RefPower": ref_interp})

        st.error("Site not found in reference.xlsx. Upload updated reference in Admin tab.")
        st.stop()

    ref_curve = load_reference(site)

    # =========================
    # PROCESS TURBINE
    # =========================
    def process_turbine(t):
        df_t = df[df["Name"] == t].copy()

        df_t = df_t[
            (df_t[wind_col] >= 3) &
            (df_t[wind_col] <= 25) &
            (df_t[power_col] > 0) &
            (df_t[pitch_col] >= -5) &
            (df_t[pitch_col] <= 5)
        ]

        if len(df_t) < 30:
            return None

        std_dev = df_t[power_col].std()
        df_t["WindBin"] = (np.floor(df_t[wind_col] / BIN_SIZE) * BIN_SIZE).round(6)

        actual = df_t.groupby("WindBin").agg(
            AvgPower=(power_col, "mean")
        ).reset_index()

        merged = ref_curve.merge(actual, on="WindBin", how="left")
        valid = merged["AvgPower"].notna()

        if valid.sum() >= 7:
            merged.loc[valid, "AvgPower"] = savgol_filter(
                merged.loc[valid, "AvgPower"],
                7,
                2
            )

        merged["Deviation_%"] = ((merged["AvgPower"] - merged["RefPower"]) / merged["RefPower"]) * 100
        avg_dev = merged["Deviation_%"].mean(skipna=True)

        return df_t, merged, avg_dev, std_dev

    # =========================
    # PLOT GRAPH (UPDATED COLORS + ORDER)
    # =========================
    def plot_graph(df_t, merged, title, dev):
        title_color = "green" if -2 <= dev <= 2 else ("orange" if dev < -2 else "red")

        fig = go.Figure()

        # 1) Scatter first (bottom)
        fig.add_trace(go.Scatter(
            x=df_t[wind_col],
            y=df_t[power_col],
            mode="markers",
            marker=dict(
                size=4,
                opacity=0.35,
                color="rgba(30, 144, 255, 0.55)"
            ),
            name="Scatter points"
        ))

        # 2) Reference second (middle)
        fig.add_trace(go.Scatter(
            x=merged["WindBin"],
            y=merged["RefPower"],
            mode="lines",
            line=dict(
                dash="dash",
                width=3,
                color="red"
            ),
            name="Reference"
        ))

        # 3) Actual last (top) - GREEN (thicker)
        fig.add_trace(go.Scatter(
            x=merged["WindBin"],
            y=merged["AvgPower"],
            mode="lines+markers",
            line=dict(
                width=6,    # <-- increase thickness (try 6 or 7)
                color="green"
            ),
            marker=dict(
                size=6,
                color="green"
            ),
            name="Actual"
        ))

        fig.update_layout(
            title=dict(
                text=f"{title} (Dev: {round(dev, 2)}%)",
                font=dict(color=title_color)
            ),
            xaxis_title="Wind Speed",
            yaxis_title="Power",
            height=500
        )

        return fig

    # =========================
    # COMMENT
    # =========================
    def generate_comment(dev):
        if dev is None:
            return "Data not available"

        dev = round(dev, 2)

        if dev < -72:
            return f"Dev: {dev}% → Extreme issue (Data unreliable)"
        elif dev < -10:
            return f"Dev: {dev}% → Severe underperformance (Blade/Dust/Yaw issue)"
        elif dev < -2:
            return f"Dev: {dev}% → Underperformance (Control/availability)"
        elif dev > 72:
            return f"Dev: {dev}% → Abnormal high (Sensor/Data issue)"
        elif dev > 8:
            return f"Dev: {dev}% → High overperformance"
        elif dev > 2:
            return f"Dev: {dev}% → Slight overperformance"
        else:
            return f"Dev: {dev}% → Normal performance"

    # =========================
    # MODE
    # =========================
    turbines = df["Name"].unique()

    if mode == "Single Turbine":
        turbines_to_show = [st.sidebar.selectbox("Select Turbine", turbines, key="single_turbine")]
    elif mode == "Compare Turbines":
        turbines_to_show = st.sidebar.multiselect("Select Turbines", turbines, key="compare_turbines")
    else:
        turbines_to_show = turbines

    # =========================
    # DISPLAY
    # =========================
    cols = st.columns(2)
    results = []
    figures = []
    i = 0

    for t in turbines_to_show:
        res = process_turbine(t)
        if not res:
            continue

        df_t, merged, dev, std = res

        with cols[i % 2]:
            fig = plot_graph(df_t, merged, t, dev)
            st.plotly_chart(fig, use_container_width=True)
            st.markdown("### Analysis")
            st.code(generate_comment(dev))

        figures.append((t, fig, generate_comment(dev)))

        if -2 <= dev <= 2:
            status = "Normal"
        elif 2 < dev <= 8:
            status = "Slight Over"
        elif dev > 8:
            status = "High Over"
        elif -10 <= dev < -2:
            status = "Under"
        elif dev < -10:
            status = "High Under"
        else:
            status = "Issue"

        results.append({
            "Turbine": t,
            "Deviation_%": round(dev, 2),
            "Status": status
        })

        i += 1

    # =========================
    # RANKING TABLE
    # =========================
    st.subheader("Turbine Ranking")

    results_df = pd.DataFrame(results)

    if not results_df.empty:
        results_df = results_df.sort_values(by="Deviation_%")

        def color_row(row):
            if row["Status"] == "Normal":
                return ['background-color: #ccffcc'] * len(row)
            elif row["Status"] == "Slight Over":
                return ['background-color: #66ff66'] * len(row)
            elif row["Status"] == "High Over":
                return ['background-color: #009933'] * len(row)
            elif row["Status"] == "Under":
                return ['background-color: #ffcc66'] * len(row)
            elif row["Status"] == "High Under":
                return ['background-color: #ff6666'] * len(row)
            else:
                return ['background-color: #cccccc'] * len(row)

        styled_table = results_df.style.apply(color_row, axis=1)
        st.dataframe(styled_table, use_container_width=True)

    # =========================
    # PDF REPORT
    # =========================
    try:
        pdf_buffer = io.BytesIO()
        pdf = canvas.Canvas(pdf_buffer, pagesize=landscape(A4))
        width, height = landscape(A4)

        if os.path.exists(logo_path):
            pdf.drawImage(logo_path, 30, height - 80, width=120, height=40)

        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(170, height - 40, "Power Curve Analytics Report")

        pdf.setFont("Helvetica", 10)
        pdf.drawString(170, height - 60, f"Site: {site}")
        pdf.drawString(170, height - 75, f"Date Range: {start_day} to {end_day}")

        y = height - 120

        for turbine, fig, comment in figures:
            if KALEIDO_AVAILABLE:
                try:
                    img = fig.to_image(format="png")
                    img_reader = ImageReader(io.BytesIO(img))

                    if y < 260:
                        pdf.showPage()
                        y = height - 60

                    pdf.drawImage(img_reader, 30, y - 220, width=360, height=200)

                    pdf.setFont("Helvetica-Bold", 11)
                    pdf.drawString(420, y - 40, turbine)

                    pdf.setFont("Helvetica", 10)
                    pdf.drawString(420, y - 60, comment)

                    y -= 240
                except Exception:
                    pass

        pdf.showPage()
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(30, height - 40, "Turbine Ranking Summary")

        y = height - 80
        pdf.setFont("Helvetica", 10)

        if not results_df.empty:
            for _, row in results_df.iterrows():
                line = f"{row['Turbine']} | {row['Deviation_%']} % | {row['Status']}"
                pdf.drawString(40, y, line)
                y -= 20

                if y < 40:
                    pdf.showPage()
                    y = height - 40

        pdf.save()
        pdf_buffer.seek(0)

        st.download_button(
            label="Download Full Dashboard Report (PDF)",
            data=pdf_buffer.getvalue(),
            file_name="WindFarm_Full_Report.pdf",
            mime="application/pdf"
        )

    except Exception as e:
        st.error("PDF generation failed")
        st.code(str(e))
