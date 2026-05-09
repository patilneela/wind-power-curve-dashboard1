import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from scipy.signal import savgol_filter
from datetime import timedelta
import os
import io

from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image,
    Table,
    TableStyle,
    PageBreak
)

from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

st.set_page_config(layout="wide")

# ---------------- LOGO ----------------
logo_path = "Envision.png"

col1, col2, col3 = st.columns([1, 2, 1])

with col2:
    if os.path.exists(logo_path):
        st.image(logo_path, width=250)

st.title("Power Curve Analytics Report")

# ---------------- CONSTANTS ----------------
BIN_SIZE = 0.5
REF_FILE = "India site Standard & Theoretical PC data 1234.xlsx"

# ---------------- SIDEBAR ----------------
uploaded_file = st.sidebar.file_uploader(
    "Upload SCADA CSV",
    type=["csv"]
)

if uploaded_file is None:
    st.warning("Upload SCADA file")
    st.stop()

# ---------------- LOAD DATA ----------------
@st.cache_data
def load_scada(file):

    df = pd.read_csv(file)

    df.columns = df.columns.str.strip()

    wind_col = [
        c for c in df.columns
        if "wind" in c.lower()
    ][0]

    power_col = [
        c for c in df.columns
        if "power" in c.lower() or "active" in c.lower()
    ][0]

    time_col = [
        c for c in df.columns
        if "time" in c.lower()
    ][0]

    df[time_col] = pd.to_datetime(
        df[time_col],
        errors="coerce"
    )

    df[wind_col] = pd.to_numeric(
        df[wind_col],
        errors="coerce"
    )

    df[power_col] = pd.to_numeric(
        df[power_col],
        errors="coerce"
    )

    df = df.dropna(
        subset=[time_col, wind_col, power_col]
    )

    df["Name"] = df["Name"].astype(str)

    return df, wind_col, power_col, time_col


df, wind_col, power_col, time_col = load_scada(uploaded_file)

# ---------------- DATE FILTER ----------------
min_date = df[time_col].min().date()
max_date = df[time_col].max().date()

date_range = st.sidebar.date_input(
    "Select Date Range",
    value=(max_date - timedelta(days=15), max_date),
    min_value=min_date,
    max_value=max_date
)

# HANDLE SINGLE DATE
if len(date_range) == 1:

    start = pd.to_datetime(date_range[0])

    end = start + pd.Timedelta(days=1)

else:

    start = pd.to_datetime(date_range[0])

    end = pd.to_datetime(date_range[1]) + pd.Timedelta(days=1)

# FILTER DATA
filtered_df = df[
    (df[time_col] >= start) &
    (df[time_col] < end)
].copy()

if filtered_df.empty:
    st.error("No data available for selected date range")
    st.stop()

st.info(f"Total Data Points: {len(filtered_df)}")

st.markdown(
    f"""
    <div style="
        background-color:#f2f2f2;
        padding:10px;
        border-radius:10px;
        font-size:18px;
        font-weight:bold;">
        Date Range:
        {start.strftime('%Y-%m-%d')}
        →
        {(end - pd.Timedelta(days=1)).strftime('%Y-%m-%d')}
    </div>
    """,
    unsafe_allow_html=True
)

# ---------------- LOAD REFERENCE ----------------
@st.cache_data
def load_reference():

    ref = pd.read_excel(REF_FILE)

    # TAKE FIRST 2 COLUMNS ONLY
    ref = ref.iloc[:, :2]

    ref.columns = ["WindBin", "RefPower"]

    ref["WindBin"] = pd.to_numeric(
        ref["WindBin"],
        errors="coerce"
    )

    ref["RefPower"] = pd.to_numeric(
        ref["RefPower"],
        errors="coerce"
    )

    ref = ref.dropna()

    return ref


ref_curve = load_reference()

# ---------------- PROCESS ----------------
def process_turbine(t):

    d = filtered_df[
        filtered_df["Name"] == t
    ].copy()

    if d.empty:
        return None

    # SCATTER DATA
    df_scatter = d.copy()

    # FILTERED CURVE DATA
    df_curve = d[
        (d[wind_col] >= 3) &
        (d[power_col] > 0)
    ].copy()

    if len(df_curve) < 20:
        return None

    # WIND BIN
    df_curve["WindBin"] = (
        np.round(df_curve[wind_col] / BIN_SIZE) * BIN_SIZE
    )

    actual = (
        df_curve
        .groupby("WindBin")[power_col]
        .mean()
        .reset_index()
    )

    actual.columns = ["WindBin", "AvgPower"]

    # MERGE
    merged = ref_curve.merge(
        actual,
        on="WindBin",
        how="left"
    )

    valid = merged["AvgPower"].notna()

    # SMOOTHING
    if valid.sum() > 5:

        try:

            merged.loc[valid, "AvgPower"] = savgol_filter(
                merged.loc[valid, "AvgPower"],
                5,
                2
            )

        except:
            pass

    # DEVIATION
    merged["Deviation_%"] = (
        (
            merged["AvgPower"] - merged["RefPower"]
        ) / merged["RefPower"]
    ) * 100

    dev = merged["Deviation_%"].mean(skipna=True)

    # AVAILABILITY
    availability = (
        len(df_curve) / len(d)
    ) * 100

    return df_scatter, merged, dev, availability

# ---------------- COMMENT ----------------
def comment(dev):

    if dev < -10:
        return "Severe underperformance", "#ff0000"

    elif dev < -2:
        return "Underperformance", "#ff9900"

    elif dev > 8:
        return "High overperformance", "#009900"

    elif dev > 2:
        return "Slight overperformance", "#66cc66"

    else:
        return "Normal", "#0066cc"

# ---------------- GRAPH ----------------
def plot_graph(df_scatter, merged, t):

    n = len(df_scatter)

    if n < 200:
        size, op = 7, 0.9

    elif n < 1000:
        size, op = 5, 0.6

    else:
        size, op = 3, 0.3

    fig = go.Figure()

    # SCATTER
    fig.add_trace(go.Scatter(
        x=df_scatter[wind_col],
        y=df_scatter[power_col],
        mode='markers',
        marker=dict(
            size=size,
            opacity=op,
            color='lightblue'
        ),
        name="SCADA Data"
    ))

    # ACTUAL CURVE
    fig.add_trace(go.Scatter(
        x=merged["WindBin"],
        y=merged["AvgPower"],
        mode='lines+markers',
        line=dict(
            color='green',
            width=3
        ),
        marker=dict(size=7),
        name="Actual Curve"
    ))

    # REFERENCE CURVE
    fig.add_trace(go.Scatter(
        x=merged["WindBin"],
        y=merged["RefPower"],
        mode='lines',
        line=dict(
            color='red',
            width=3,
            dash='dash'
        ),
        name="Reference Curve"
    ))

    fig.update_layout(

        title=f"Power Curve Analysis - {t}",

        xaxis_title="Wind Speed (m/s)",

        yaxis_title="Power Output (kW)",

        height=600,

        template="plotly_white",

        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5
        )
    )

    return fig

# ---------------- DISPLAY ----------------
results = []
images = []

turbines = sorted(filtered_df["Name"].unique())

for t in turbines:

    res = process_turbine(t)

    if res is None:
        continue

    df_scatter, merged, dev, avail = res

    fig = plot_graph(df_scatter, merged, t)

    st.plotly_chart(
        fig,
        use_container_width=True
    )

    comm, color = comment(dev)

    st.markdown(
        f"""
        <div style="
            background-color:{color};
            padding:12px;
            border-radius:10px;
            color:white;
            font-size:18px;
            font-weight:bold;
            margin-bottom:25px;">

            Comment: {comm}
            <br>

            Deviation: {round(dev,2)}%
            <br>

            Availability: {round(avail,1)}%
        </div>
        """,
        unsafe_allow_html=True
    )

    # ---------- FIXED DOWNLOAD LOGIC ----------
    try:

        img_bytes = fig.to_image(
            format="png",
            width=1400,
            height=700,
            scale=2
        )

        images.append((
            t,
            img_bytes,
            dev,
            avail,
            comm,
            color
        ))

    except Exception as e:

        st.warning(
            f"Graph image export issue: {e}"
        )

    results.append([
        t,
        round(dev, 2),
        round(avail, 1)
    ])

# ---------------- TABLE ----------------
st.subheader("Turbine Ranking")

df_res = pd.DataFrame(
    results,
    columns=[
        "Turbine",
        "Deviation",
        "Availability"
    ]
)

st.dataframe(
    df_res,
    use_container_width=True
)

# ---------------- PDF GENERATION ----------------
def create_pdf():

    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        rightMargin=20,
        leftMargin=20,
        topMargin=20,
        bottomMargin=20
    )

    styles = getSampleStyleSheet()

    elements = []

    # LOGO
    if os.path.exists(logo_path):

        elements.append(
            Image(
                logo_path,
                width=180,
                height=60
            )
        )

        elements.append(Spacer(1, 20))

    # HEADER
    elements.append(
        Paragraph(
            "Power Curve Analytics Report",
            styles["Title"]
        )
    )

    elements.append(Spacer(1, 10))

    elements.append(
        Paragraph(
            f"Date Range: "
            f"{start.strftime('%Y-%m-%d')} "
            f"to "
            f"{(end - pd.Timedelta(days=1)).strftime('%Y-%m-%d')}",
            styles["Normal"]
        )
    )

    elements.append(
        Paragraph(
            f"Total Data Points: {len(filtered_df)}",
            styles["Normal"]
        )
    )

    elements.append(Spacer(1, 20))

    # TURBINE PAGES
    for t, img, dev, avail, comm, color in images:

        elements.append(
            Paragraph(
                f"Turbine: {t}",
                styles["Heading2"]
            )
        )

        elements.append(
            Paragraph(
                f"Deviation: {round(dev,2)}%",
                styles["Normal"]
            )
        )

        elements.append(
            Paragraph(
                f"Availability: {round(avail,1)}%",
                styles["Normal"]
            )
        )

        elements.append(Spacer(1, 5))

        # COMMENT BOX
        comment_table = Table(
            [[f"Comment: {comm}"]],
            colWidths=[450]
        )

        comment_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), color),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
        ]))

        elements.append(comment_table)

        elements.append(Spacer(1, 15))

        # GRAPH IMAGE
        img_file = io.BytesIO(img)

        elements.append(
            Image(
                img_file,
                width=500,
                height=280
            )
        )

        elements.append(Spacer(1, 25))

        elements.append(PageBreak())

    # SUMMARY TABLE
    elements.append(
        Paragraph(
            "Turbine Ranking",
            styles["Heading2"]
        )
    )

    elements.append(Spacer(1, 10))

    table_data = [
        ["Turbine", "Deviation", "Availability"]
    ] + results

    table = Table(table_data)

    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold')
    ]))

    elements.append(table)

    # BUILD PDF
    doc.build(elements)

    buffer.seek(0)

    return buffer.getvalue()

# ---------------- DOWNLOAD ----------------
try:

    pdf_bytes = create_pdf()

    st.download_button(
        label="Download Full Dashboard Report (PDF)",
        data=pdf_bytes,
        file_name="WindFarm_Full_Report.pdf",
        mime="application/pdf"
    )

except Exception as e:

    st.error(f"PDF Generation Error: {e}")

    st.info(
        "Add this in requirements.txt:\n\nkaleido"
    )
