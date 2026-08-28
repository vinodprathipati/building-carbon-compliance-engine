"""LL97 building compliance explorer. Search by Property ID; reads
entirely from gold_building_compliance_projections (Postgres) — no Spark
dependency at runtime, since Gold has already computed everything this
page shows.

    streamlit run streamlit_app.py
"""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go
import psycopg
import streamlit as st

from disclosure_pipeline.config import Settings

# Categorical palette, fixed assignment per fuel (never re-ordered per
# building) so a given fuel is always the same color across searches.
FUEL_COLORS: dict[str, str] = {
    "Grid Electricity": "#2a78d6",
    "Natural Gas": "#eb6834",
    "District Steam": "#1baf7a",
    "Fuel Oil #2": "#eda100",
    "Fuel Oil #4": "#e87ba4",
    "Distillate Fuel Oil No. 1": "#008300",
    "Diesel": "#4a3aa7",
    "Propane": "#e34948",
}

# Status palette (fixed, never themed).
STATUS_COLOR = {"compliant": "#0ca30c", "exceeds": "#d03b3b", "cap_unavailable": "#fab219"}
STATUS_LABEL = {"compliant": "Compliant", "exceeds": "Exceeds cap", "cap_unavailable": "Cap data unavailable"}
CAP_BAR_COLOR = "#9a9a95"  # neutral gray — cap is a reference value, not a status

FUEL_USAGE_FIELDS = [
    ("electricity_use_kwh", "Grid Electricity", "kWh"),
    ("natural_gas_use_kbtu", "Natural Gas", "kBtu"),
    ("district_steam_use_kbtu", "District Steam", "kBtu"),
    ("fuel_oil_2_use_kbtu", "Fuel Oil #2", "kBtu"),
    ("fuel_oil_4_use_kbtu", "Fuel Oil #4", "kBtu"),
    ("fuel_oil_1_use_kbtu", "Distillate Fuel Oil No. 1", "kBtu"),
    ("diesel_2_use_kbtu", "Diesel", "kBtu"),
    ("propane_use_kbtu", "Propane", "kBtu"),
    ("fuel_oil_5_6_use_kbtu", "Fuel Oil #5 & 6", "kBtu"),
]


@st.cache_resource
def get_connection() -> psycopg.Connection:
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    return psycopg.connect(dsn, autocommit=True)


def fetch_building(property_id: str) -> list[dict[str, Any]]:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT property_id, bbl, property_name, borough, primary_property_type,
                   gross_floor_area_ft, year_ending, reported_emissions_tco2e,
                   electricity_use_kwh, natural_gas_use_kbtu, fuel_oil_1_use_kbtu,
                   fuel_oil_2_use_kbtu, fuel_oil_4_use_kbtu, fuel_oil_5_6_use_kbtu,
                   diesel_2_use_kbtu, propane_use_kbtu, district_steam_use_kbtu,
                   period_start, period_end, status, cap_tco2e, actual_emissions_tco2e,
                   excess_emissions_tco2e, potential_penalty_usd
            FROM gold_building_compliance_projections
            WHERE property_id = %s
            ORDER BY period_start
            """,
            (property_id,),
        )
        columns = [d.name for d in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def render_status_banner(rows: list[dict[str, Any]]) -> None:
    exceeding = [r for r in rows if r["status"] == "exceeds"]
    if exceeding:
        first = exceeding[0]
        max_penalty = max(r["potential_penalty_usd"] or 0 for r in exceeding)
        st.error(
            f"🔴 **Exceeds emissions cap starting {first['period_start']}–{first['period_end']}** "
            f"— up to **${max_penalty:,.0f}/year** potential penalty",
            icon="🔴",
        )
    elif all(r["status"] == "cap_unavailable" for r in rows):
        st.warning(
            f"🟡 **Emissions cap unavailable** for property type "
            f"'{rows[0]['primary_property_type']}' — likely mixed-use, not yet supported.",
            icon="🟡",
        )
    else:
        last = rows[-1]
        st.success(f"🟢 **Compliant through {last['period_end']}** — no LL97 penalty exposure projected.", icon="🟢")


def render_building_summary(row: dict[str, Any]) -> None:
    # st.metric renders a big value under a small label — right for a KPI
    # number, wrong for text like a property name or address (oversized
    # and visually mismatched next to the small label). A plain
    # caption + bold pair keeps label and value proportionate.
    gfa = row["gross_floor_area_ft"]
    fields = [
        ("Property", row["property_name"] or "—"),
        ("BBL", row["bbl"] or "—"),
        ("Borough", row["borough"] or "—"),
        ("Property type", row["primary_property_type"] or "—"),
        ("Gross floor area", f"{gfa:,.0f} sf" if gfa else "—"),
        ("Reporting year", row["year_ending"] or "—"),
    ]
    cols = st.columns(len(fields))
    for col, (label, value) in zip(cols, fields):
        col.caption(label)
        col.markdown(f"**{value}**")


def render_fuel_mix_pie(row: dict[str, Any]) -> None:
    labels, values, colors, hover = [], [], [], []
    for field, fuel_type, unit in FUEL_USAGE_FIELDS:
        usage = row.get(field)
        if not usage:
            continue
        labels.append(fuel_type)
        values.append(usage)
        colors.append(FUEL_COLORS.get(fuel_type, "#9a9a95"))
        hover.append(f"{fuel_type}<br>{usage:,.0f} {unit}")

    if not values:
        st.info("No fuel usage reported for this building.")
        return

    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            marker=dict(colors=colors, line=dict(color="#fcfcfb", width=2)),
            hovertext=hover,
            hoverinfo="text",
            textinfo="label+percent",
            sort=False,
        )
    )
    fig.update_layout(
        title="Fuel usage mix (reported year)",
        margin=dict(t=40, b=10, l=10, r=10),
        showlegend=True,
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Slice size reflects each fuel's own raw usage in its native unit (kWh vs. kBtu are not "
        "directly comparable) — hover a slice for its exact value and unit."
    )


def render_compliance_chart(rows: list[dict[str, Any]]) -> None:
    period_labels = [f"{r['period_start']}–{r['period_end']}" for r in rows]
    caps = [r["cap_tco2e"] for r in rows]
    actuals = [r["actual_emissions_tco2e"] for r in rows]
    actual_colors = [STATUS_COLOR.get(r["status"], "#9a9a95") for r in rows]

    fig = go.Figure()
    fig.add_bar(name="Cap", x=period_labels, y=caps, marker_color=CAP_BAR_COLOR)
    fig.add_bar(
        name="Actual",
        x=period_labels,
        y=actuals,
        marker_color=actual_colors,
        hovertext=[STATUS_LABEL.get(r["status"], r["status"]) for r in rows],
        hoverinfo="x+y+text",
    )
    fig.update_layout(
        title="Emissions cap vs. actual by compliance period",
        yaxis_title="tCO2e",
        barmode="group",
        margin=dict(t=40, b=10, l=10, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("🟢 compliant · 🔴 exceeds cap · 🟡 cap unavailable — bar color follows each period's status.")


def render_detail_table(rows: list[dict[str, Any]]) -> None:
    display_rows = [
        {
            "Period": f"{r['period_start']}–{r['period_end']}",
            "Status": STATUS_LABEL.get(r["status"], r["status"]),
            "Cap (tCO2e)": r["cap_tco2e"],
            "Actual (tCO2e)": r["actual_emissions_tco2e"],
            "Excess (tCO2e)": r["excess_emissions_tco2e"],
            "Potential penalty ($)": r["potential_penalty_usd"],
        }
        for r in rows
    ]
    st.dataframe(display_rows, use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(page_title="Building Carbon Compliance Engine", page_icon="🏢", layout="wide")
    st.title("🏢 Building Carbon Compliance Engine")
    st.caption("NYC Local Law 97 — search a building to see its emissions profile and compliance projection.")

    property_id = st.text_input("Property ID", placeholder="e.g. 12915497")
    search = st.button("Search", type="primary")

    if not (search and property_id):
        st.stop()

    rows = fetch_building(property_id.strip())
    if not rows:
        st.warning(
            f"No compliance projection found for Property ID **{property_id}**. "
            "It may not be a covered building, or the ID may be incorrect."
        )
        st.stop()

    render_status_banner(rows)
    render_building_summary(rows[0])
    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        render_fuel_mix_pie(rows[0])
    with col2:
        render_compliance_chart(rows)

    with st.expander("Full period-by-period detail"):
        render_detail_table(rows)


if __name__ == "__main__":
    main()
