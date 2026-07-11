"""
Shanghai Entertainment Dashboard
================================
An interactive explorer for the Leisure_ALL historical database of Shanghai
theatre, opera and cinema programmes (1907-1991), reconstructed from a
FileMaker export into three linked tables: shows, performed_items, performers.

Run locally:
    pip install -r requirements.txt
    streamlit run app.py
"""

from __future__ import annotations

import os
import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "data", "shanghai_entertainment.db")

st.set_page_config(
    page_title="Shanghai Entertainment Dashboard",
    page_icon="🎭",
    layout="wide",
)

# --------------------------------------------------------------------------
# Data access
# --------------------------------------------------------------------------


@st.cache_resource
def get_conn() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        st.error(
            f"Database not found at {DB_PATH}. "
            "Run `python scripts/data_prep.py` first."
        )
        st.stop()
    # Open read-only + immutable: the dashboard never writes, and this avoids
    # creating journal/WAL/lock files, which lets it work on cloud-synced or
    # network filesystems (Dropbox, iCloud) that don't support SQLite locking.
    uri = f"file:{DB_PATH}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True, check_same_thread=False)


@st.cache_data
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, get_conn(), params=params)


@st.cache_data
def bounds() -> tuple[int, int]:
    df = q("SELECT MIN(year) lo, MAX(year) hi FROM shows WHERE year IS NOT NULL")
    return int(df.lo[0]), int(df.hi[0])


@st.cache_data
def genre_options() -> list[str]:
    df = q(
        "SELECT genre FROM performed_items WHERE genre<>'' "
        "GROUP BY genre ORDER BY COUNT(*) DESC"
    )
    return df.genre.tolist()


@st.cache_data
def venue_options() -> list[str]:
    df = q(
        "SELECT venue FROM shows WHERE venue<>'' "
        "GROUP BY venue ORDER BY COUNT(*) DESC LIMIT 400"
    )
    return df.venue.tolist()


def where_clause(years, genres, venues):
    """Build a SQL WHERE fragment + params for the item-level joined view."""
    conds, params = ["s.year BETWEEN ? AND ?"], [years[0], years[1]]
    if genres:
        conds.append("pi.genre IN (%s)" % ",".join("?" * len(genres)))
        params += genres
    if venues:
        conds.append("s.venue IN (%s)" % ",".join("?" * len(venues)))
        params += venues
    return " AND ".join(conds), tuple(params)


# --------------------------------------------------------------------------
# Sidebar filters
# --------------------------------------------------------------------------

lo, hi = bounds()
st.sidebar.title("🎭 Filters")
years = st.sidebar.slider("Year range", lo, hi, (lo, hi))
sel_genres = st.sidebar.multiselect("Genre", genre_options())
sel_venues = st.sidebar.multiselect("Venue (top 400)", venue_options())
st.sidebar.caption(
    "Data: Leisure_ALL historical database of Shanghai entertainment "
    "programmes. Dates and prices are transcribed from period newspapers "
    "(申报, 新闻报, …)."
)

WHERE, PARAMS = where_clause(years, sel_genres, sel_venues)

# --------------------------------------------------------------------------
# Header + KPIs
# --------------------------------------------------------------------------

st.title("Shanghai Entertainment, 1907–1991")
st.caption(
    "Theatre, opera, and cinema programmes transcribed from period newspapers."
)

kpi = q(
    f"""
    SELECT COUNT(DISTINCT pi.item_id)  AS items,
           COUNT(DISTINCT s.show_id)   AS shows,
           COUNT(DISTINCT s.venue)     AS venues
    FROM performed_items pi
    JOIN shows s ON pi.show_id = s.show_id
    WHERE {WHERE}
    """,
    PARAMS,
)
perf_count = q(
    f"""
    SELECT COUNT(DISTINCT pf.performer_name) AS performers
    FROM performers pf
    JOIN performed_items pi ON pf.item_id = pi.item_id
    JOIN shows s ON pi.show_id = s.show_id
    WHERE {WHERE} AND pf.performer_name <> ''
    """,
    PARAMS,
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Performed items", f"{int(kpi['items'][0]):,}")
c2.metric("Shows", f"{int(kpi['shows'][0]):,}")
c3.metric("Distinct venues", f"{int(kpi['venues'][0]):,}")
c4.metric("Named performers", f"{int(perf_count['performers'][0]):,}")

tab_time, tab_genre, tab_venue, tab_perf, tab_browse = st.tabs(
    ["📈 Over time", "🎬 Genres", "🏛 Venues", "⭐ Performers", "🔎 Browse"]
)

# --------------------------------------------------------------------------
# Over time
# --------------------------------------------------------------------------

with tab_time:
    df = q(
        f"""
        SELECT s.year AS year, COUNT(*) AS items
        FROM performed_items pi
        JOIN shows s ON pi.show_id = s.show_id
        WHERE {WHERE} AND s.year IS NOT NULL
        GROUP BY s.year ORDER BY s.year
        """,
        PARAMS,
    )
    if df.empty:
        st.info("No data for the current filters.")
    else:
        fig = px.area(
            df, x="year", y="items",
            labels={"year": "Year", "items": "Performed items"},
            title="Performed items per year",
        )
        fig.update_traces(line_color="#c0392b")
        st.plotly_chart(fig, width="stretch")
        st.caption(
            "Gaps and spikes reflect newspaper coverage and archival "
            "completeness as much as real activity."
        )

# --------------------------------------------------------------------------
# Genres
# --------------------------------------------------------------------------

with tab_genre:
    col_a, col_b = st.columns([1, 1])
    with col_a:
        df = q(
            f"""
            SELECT pi.genre AS genre, COUNT(*) AS items
            FROM performed_items pi
            JOIN shows s ON pi.show_id = s.show_id
            WHERE {WHERE} AND pi.genre <> ''
            GROUP BY pi.genre ORDER BY items DESC LIMIT 20
            """,
            PARAMS,
        )
        if not df.empty:
            fig = px.bar(
                df.sort_values("items"), x="items", y="genre",
                orientation="h", title="Top genres",
                labels={"items": "Performed items", "genre": ""},
            )
            fig.update_traces(marker_color="#2c3e50")
            st.plotly_chart(fig, width="stretch")
    with col_b:
        top = df.genre.head(6).tolist() if not df.empty else []
        if top:
            ph = ",".join("?" * len(top))
            trend = q(
                f"""
                SELECT s.year AS year, pi.genre AS genre, COUNT(*) AS items
                FROM performed_items pi
                JOIN shows s ON pi.show_id = s.show_id
                WHERE {WHERE} AND s.year IS NOT NULL AND pi.genre IN ({ph})
                GROUP BY s.year, pi.genre ORDER BY s.year
                """,
                PARAMS + tuple(top),
            )
            fig = px.line(
                trend, x="year", y="items", color="genre",
                title="Genre trends (top 6)",
                labels={"year": "Year", "items": "Items", "genre": "Genre"},
            )
            st.plotly_chart(fig, width="stretch")

# --------------------------------------------------------------------------
# Venues
# --------------------------------------------------------------------------

with tab_venue:
    df = q(
        f"""
        SELECT s.venue AS venue, COUNT(DISTINCT s.show_id) AS shows,
               COUNT(*) AS items
        FROM performed_items pi
        JOIN shows s ON pi.show_id = s.show_id
        WHERE {WHERE} AND s.venue <> ''
        GROUP BY s.venue ORDER BY items DESC LIMIT 25
        """,
        PARAMS,
    )
    if df.empty:
        st.info("No data for the current filters.")
    else:
        fig = px.bar(
            df.sort_values("items"), x="items", y="venue", orientation="h",
            title="Busiest venues", labels={"items": "Performed items", "venue": ""},
            hover_data=["shows"],
        )
        fig.update_traces(marker_color="#16a085")
        fig.update_layout(height=650)
        st.plotly_chart(fig, width="stretch")
        st.dataframe(
            df.rename(columns={"venue": "Venue", "shows": "Shows",
                               "items": "Performed items"}),
            width="stretch", hide_index=True,
        )

# --------------------------------------------------------------------------
# Performers
# --------------------------------------------------------------------------

with tab_perf:
    st.subheader("Search a performer")
    name = st.text_input("Performer name (Chinese)", placeholder="e.g. 麒麟童")
    if name:
        appearances = q(
            """
            SELECT s.date_iso AS date, s.venue AS venue, pi.title AS title,
                   pi.genre AS genre, pi.show_time AS show_time
            FROM performers pf
            JOIN performed_items pi ON pf.item_id = pi.item_id
            JOIN shows s ON pi.show_id = s.show_id
            WHERE pf.performer_name = ?
            ORDER BY s.date_iso
            """,
            (name,),
        )
        st.write(f"**{len(appearances):,}** appearances found for “{name}”.")
        if not appearances.empty:
            yr = appearances.copy()
            yr["year"] = pd.to_datetime(
                yr["date"], errors="coerce"
            ).dt.year
            byyear = yr.dropna(subset=["year"]).groupby("year").size()
            if not byyear.empty:
                st.plotly_chart(
                    px.bar(x=byyear.index, y=byyear.values,
                           labels={"x": "Year", "y": "Appearances"},
                           title=f"{name} — appearances per year"),
                    width="stretch",
                )
            st.dataframe(appearances, width="stretch", hide_index=True)

    st.divider()
    st.subheader("Most frequently billed performers")
    top = q(
        f"""
        SELECT pf.performer_name AS performer, COUNT(*) AS appearances
        FROM performers pf
        JOIN performed_items pi ON pf.item_id = pi.item_id
        JOIN shows s ON pi.show_id = s.show_id
        WHERE {WHERE} AND pf.performer_name <> ''
        GROUP BY pf.performer_name ORDER BY appearances DESC LIMIT 30
        """,
        PARAMS,
    )
    st.dataframe(
        top.rename(columns={"performer": "Performer",
                            "appearances": "Appearances"}),
        width="stretch", hide_index=True,
    )

# --------------------------------------------------------------------------
# Browse / search items
# --------------------------------------------------------------------------

with tab_browse:
    st.subheader("Search performed items")
    term = st.text_input("Title contains", placeholder="e.g. 杨乃武")
    conds, params = [WHERE], list(PARAMS)
    if term:
        conds.append("pi.title LIKE ?")
        params.append(f"%{term}%")
    sql = f"""
        SELECT s.date_iso AS date, s.venue AS venue, pi.title AS title,
               pi.genre AS genre, pi.show_time AS show_time,
               pi.advertising_label AS label, s.ticket_price AS price,
               s.source AS source
        FROM performed_items pi
        JOIN shows s ON pi.show_id = s.show_id
        WHERE {' AND '.join(conds)}
        ORDER BY s.date_iso
        LIMIT 2000
    """
    rows = q(sql, tuple(params))
    st.write(f"Showing up to 2,000 of the matching items ({len(rows):,} shown).")
    st.dataframe(rows, width="stretch", hide_index=True)
    st.download_button(
        "⬇ Download these results (CSV)",
        rows.to_csv(index=False).encode("utf-8-sig"),
        file_name="shanghai_entertainment_query.csv",
        mime="text/csv",
    )
