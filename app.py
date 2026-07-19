"""
Shanghai Entertainment Dashboard
================================
An interactive explorer for the SHBKYL historical database of Shanghai
theater, opera, and cinema programs (1907-1966), reconstructed from a
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
    # Cap the upper bound at 1966: the database ends in 1966, and a couple of
    # stray records with later years should not stretch the slider.
    return int(df.lo[0]), min(int(df.hi[0]), 1966)


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


@st.cache_data
def show_meta(show_id: str) -> pd.DataFrame:
    """Show-level metadata for a single show_id."""
    return q(
        "SELECT date_iso, venue, ticket_price, source "
        "FROM shows WHERE show_id = ?",
        (show_id,),
    )


@st.cache_data
def show_items(show_id: str) -> pd.DataFrame:
    """All performed items belonging to one show, with performers per item.

    This is the equivalent of the FileMaker 'Show' button: from any single
    performed item it reconstitutes the full set of items on the same bill.
    """
    return q(
        """
        SELECT pi.title                                   AS "Title",
               pi.genre                                   AS "Genre",
               pi.show_time                               AS "Show time",
               pi.advertising_label                       AS "Label",
               (SELECT GROUP_CONCAT(pf.performer_name, '、')
                  FROM performers pf
                 WHERE pf.item_id = pi.item_id
                   AND pf.performer_name <> '')           AS "Performers"
        FROM performed_items pi
        WHERE pi.show_id = ?
        ORDER BY pi.item_id
        """,
        (show_id,),
    )


def where_clause(years, genres, venues, performer):
    """Build a SQL WHERE fragment + params for the item-level joined view."""
    conds, params = ["s.year BETWEEN ? AND ?"], [years[0], years[1]]
    if genres:
        conds.append("pi.genre IN (%s)" % ",".join("?" * len(genres)))
        params += genres
    if venues:
        conds.append("s.venue IN (%s)" % ",".join("?" * len(venues)))
        params += venues
    if performer:
        conds.append(
            "pi.item_id IN (SELECT item_id FROM performers "
            "WHERE performer_name LIKE ?)"
        )
        params.append(f"%{performer}%")
    return " AND ".join(conds), tuple(params)


# --------------------------------------------------------------------------
# Sidebar filters
# --------------------------------------------------------------------------

lo, hi = bounds()
st.sidebar.title("🎭 Filters")
years = st.sidebar.slider("Year range", lo, hi, (lo, hi))
sel_genres = st.sidebar.multiselect("Genre", genre_options())
sel_venues = st.sidebar.multiselect("Venue (top 400)", venue_options())
sel_performer = st.sidebar.text_input("Performer name", placeholder="e.g. 麒麟童")

_cover = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "Leisure_Book_Cover.jpg")
if os.path.exists(_cover):
    st.sidebar.image(
        _cover,
        caption="Jiang Jin (ed.), 二十世纪上海报刊娱乐版广告资料长编 "
                "(Shanghai Culture Publishing House, 2015)",
        width="stretch",
    )

WHERE, PARAMS = where_clause(years, sel_genres, sel_venues, sel_performer)

# --------------------------------------------------------------------------
# Header + KPIs
# --------------------------------------------------------------------------

st.title("Shanghai Entertainment, 1907–1966")
st.caption(
    "Theater, opera, and cinema programs transcribed from "
    "newspaper advertisements."
)
st.caption(
    "Compiled by Christian Henriot (Aix-Marseille University) and "
    "Jiang Jin 姜进 (East China Normal University 华东师范大学)."
)

kpi = q(
    f"""
    SELECT COUNT(*)                    AS items,
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

(tab_about, tab_guide, tab_time, tab_genre, tab_venue, tab_perf,
 tab_browse) = st.tabs(
    ["📖 About", "🧭 How to use", "📈 Over time", "🎬 Genres", "🏛 Venues",
     "⭐ Performers", "🔎 Browse"]
)

# --------------------------------------------------------------------------
# About
# --------------------------------------------------------------------------

with tab_about:
    st.markdown(
        """
## The 二十世纪上海报刊娱乐版广告资料 database (1907–1966)

### Origin and credit

The 二十世纪上海报刊娱乐版广告资料 (1907–1966) database (hereafter **SHBKYL**)
is the online version of the four-volume compendium edited by Jiang Jin (姜进)
and published as 二十世纪上海报刊娱乐版广告资料长编: 1907–1966 (Ershi shiji
Shanghai baokan yuleban guanggao ziliao changbian, "Compendium of advertising
materials for entertainment in twentieth-century Shanghai newspapers") by the
Shanghai Culture Publishing House (上海文化出版社) in 2015.

Commercial entertainment — opera, cinema, dancing, and more — was a major facet
of urban life. In the late imperial and republican eras, Shanghai played a
central role in the rise of modern forms of entertainment and their diffusion
across the country. The city was the cradle of Chinese cinema, spoken drama,
and symphonic music. Entertainment facilities multiplied and relentlessly
rejuvenated leisure through a bewildering range of genres. This database
documents the evolution of entertainment in Shanghai through advertisements in
four major newspapers over six decades. It is built on a unique dataset that
traces tens of thousands of shows and performances, day and night, throughout
the city and its entertainment facilities. This approach supports a move toward
a new form of data-rich cultural history.

SHBKYL is a unique and invaluable resource for the study of leisure and
entertainment in Shanghai between 1907 and 1966. The data was collected from
four major newspapers: *Shenbao* (申報, 1907–1949), *Xinwenbao* (新聞報,
1907–1949), *Xinwen ribao* (新聞日報, 1949–1959), and *Jiefang ribao* (解放日報,
1960–1966). Jiang Jin directed the collection, compilation, and curation of the
data that eventually became four print volumes.

The database is currently entirely in Chinese. There is a plan to add pinyin for
the names of performing sites and actors and for the titles of performed items,
but this will not happen in the short term.

### Method and challenges

The challenge was how to handle the sheer volume of entertainment advertisements
in Shanghai newspapers. Collection was therefore based on sampling. For each
newspaper, the team took the first day of every month, plus the issues for the
New Year (中西), the Duanwu Festival (端午), the Mid-Autumn Festival (中秋),
National Day (国庆节, for the *Shenbao* only), and other commemorative days. Even
so, the volume of information remained considerable, and it was impossible to
record everything in the advertisements. The team chose to focus on the major
fields: location, program, ticket price, date, facility, genre (as indicated in
the source), actors, advertising label, and page.

One of the main difficulties was the lack of access to the original newspapers.
Microfilm was used for the *Xinwenbao* (新闻报), and for the *Shenbao* (申报) the
source was the reduced-format reprint collection published in the 1980s. Blurry
text and missing pages were recurring problems (notably for the *Jiefang ribao*
解放日报 and *Xinwen ribao* 新闻日报). Some advertising texts were themselves
unclear, at least to a present-day historian-reader, and the advertisements
sometimes contained erroneous characters. A further recurring problem was the
use of short names for entertainment facilities, which created ambiguities when
two different facilities shared the same short name (for example, 新华 for
新华电影院).

The database also has biases. The visual dimension of the advertisements is
entirely lost — especially differences in the size and placement of
advertisements in the newspapers. This is the price of a fully searchable
database; no attempt was made to collect the original images, given the
impossibility of doing so with the sources used. Another bias is that the
database includes only entertainment activities for which the performing sites
published advertisements. Although advertising clearly improved the chances of
attracting spectators, the database probably misses activities that took place
but were not advertised, or that were advertised on dates other than the sampled
days.

The number of advertisements published depended on several factors: the number
of facilities, the growth of entertainment practices, marketing decisions, and
so on. The table below shows the distribution of advertisements by decade
between 1907 and 1966.
        """
    )

    _decades = pd.DataFrame(
        {
            "Period": ["1907–1909", "1910–1919", "1920–1929", "1930–1939",
                       "1940–1949", "1950–1959", "1960–1966"],
            "Advertisements": [611, 11664, 29922, 41739, 17042, 24070, 10325],
        }
    )
    _decades["Advertisements"] = _decades["Advertisements"].map("{:,}".format)
    st.table(_decades.set_index("Period"))

    st.markdown(
        """
### From print to database

When the project was first designed, it was conceived as a book, not a database.
The information was collected in MS Word files in the form of tables, but none of
these tables could be automatically transposed or exported to tabular data. In
2014, during the final editing phase of the published volumes, Jiang Jin and
Christian Henriot began discussing the creation of a database. Christian Henriot
proposed building it in FileMaker and brought in Jean-Pierre Dedieu, a
programming historian (of early modern Spain) with deep knowledge of FileMaker.
The transformation proceeded in two stages. First, students copied the basic
blocks of information from the Word files into a simple database template, to
minimize the risk of errors; this stage allowed the data to be processed
internally through automatic routines that split separable fields and helped
design the final data-entry template. In the second stage, students copied and
pasted the remaining, unsplit data from the Word files into the final template.

SHBKYL inevitably contains mistakes and typos. Some data remains undistributed,
and there are occasional font-size issues. We welcome suggestions for
corrections at **enpmuc[at]gmail.com**.

### What's in it?

As a result of the transformation, SHBKYL grew into a database of **139,655
performed items** and **80,554 shows**. Each entry represents a unique performed
item, which may be part of a show. The shows took place at 818 different
performing sites, almost all of which have been located in the city (756
facilities); only 978 performances took place in unknown or undetermined
locations.

The role and importance of entertainment facilities varied greatly. The Great
World (大世界) was a powerful entertainment engine: with 14,991 shows, it
accounted for almost 10 percent of all shows in the whole period. The table below
lists the 18 facilities that offered more than 1,000 shows across the period.
There was clearly a hierarchy of entertainment facilities in Shanghai.
        """
    )

    _facilities = pd.DataFrame(
        {
            "Facility": ["大世界", "先施乐园", "天蟾舞台", "小世界", "新世界",
                         "新新屋顶花园", "福安游艺场", "永安天韵楼", "共舞台",
                         "大舞台", "黄金大戏院", "神仙世界", "大新游乐场",
                         "东方书场", "丹桂第一台", "新舞台", "上海大戏院",
                         "国泰大戏院"],
            "Shows": [14991, 4845, 4810, 4104, 4031, 3165, 2835, 2548, 2528,
                      2351, 2190, 2096, 2049, 1919, 1604, 1476, 1068, 1067],
        }
    )
    _facilities["Shows"] = _facilities["Shows"].map("{:,}".format)
    st.table(_facilities.set_index("Facility"))

    st.markdown(
        """
Shows took place mostly in the evening, but this varied greatly by genre.
Beijing opera was played almost equally in the daytime (53%) and the evening
(47%), but for cinema, women's Beijing opera, Shanghai opera (沪剧), and circus
(杂技), most shows — about 80% on average — took place during the daytime. These
are of course averages for the entire period, and actual practices must have
evolved over time.

SHBKYL records **13,700 unique actors**, very unevenly distributed by number of
mentions. For instance, 8,376 actors are mentioned only once and 2,265 only
twice. A more limited group of 1,125 actors are mentioned more than five times,
and a narrow group of 255 more than twenty times. Within the latter, the true
celebrities number only 40 individuals with more than fifty mentions.

The sources record a bewildering **589 genres**, although some items are really a
specific attraction rather than a genre as such (for example, 飞车, "flying car,"
or a type of sport). Many terms could be grouped together to refine and reduce
the number of genres and produce more meaningful statistics, but SHBKYL records
genres as they appeared in the source.

The spatial dimension of entertainment and its evolution is one of the most
fascinating aspects that these records make it possible to explore. That cannot
be presented in this introduction, but the
[Virtual Shanghai](https://www.virtualshanghai.net) platform provides a whole
collection of maps on the distribution of performing sites across the city.
        """
    )

# --------------------------------------------------------------------------
# How to use
# --------------------------------------------------------------------------

with tab_guide:
    st.markdown(
        """
## Using this database

This online version offers a focused search and browsing interface. An
advanced search function is planned. The original FileMaker database supports a
wider range of queries; **for in-depth research, please contact us at
enpmuc[at]gmail.com**.

### The interface at a glance

- **Left sidebar — Filters.** Four filters narrow the data: **Year range**,
  **Genre**, **Venue**, and **Performer name**. They combine together (all
  conditions apply at once) and affect every tab except this guide and *About*.
  Leave a filter empty to place no restriction on it.
- **Summary counts.** The four figures below the title — performed items,
  shows, distinct venues, and named performers — update live as you change the
  filters.
- **Tabs.** *Over time*, *Genres*, and *Venues* give aggregate views;
  *Performers* and *Browse* let you search individual records.

### Searching

- To search by **title**, open the **🔎 Browse** tab and type into
  "Title contains" (for example, 杨乃武). Combine it with the sidebar filters to
  refine the results.
- To search by **performer**, either type a name into the sidebar
  "Performer name" field (which filters the whole dashboard) or use the exact
  search box in the **⭐ Performers** tab, which also charts that performer's
  appearances year by year.
- Any result table can be exported: use **⬇ Download these results (CSV)** in
  the Browse tab.

### Key concepts

- **Performed item (entry).** Each entry in the database represents a unique
  performance — one film, one opera, one act, and so on.
- **Show.** A show may be a single performance (one film, a whole opera) or a
  set of performances. It was common, for instance, to bill several parts of
  different operas together. Shows were split into individual performed items,
  but the interface can reconstitute the full set.

### Reconstituting a show (the FileMaker "Show" button)

In both the **Browse** and **Performers** tabs, **click any row** in a results
table. A panel opens below showing the complete show that item belonged to —
the venue, date, and ticket price, followed by every performed item on that
bill with its genre, day/evening slot, advertising label, and performers. This
reproduces the "Show" button of the original database. Selecting a different
row switches to that item's show; the results table above is the equivalent of
the "Unique" (single-item) view.

### The fields in this version

**Show (performance-site) information**

- **Identifier of the show** — unique ID grouping items performed together.
- **Date of the show** — the exact date recorded in the source.
- **Name of the facility (venue)** — the performing site as given in the source
  (theater, teahouse, amusement hall, etc.).
- **Ticket price** — as advertised.
- **Source** — the newspaper, date, and page of the advertisement.

**Performed-item information**

- **Identifier of the performed item** — unique ID of the individual item.
- **Title** — the film, opera, or piece performed.
- **Genre** — as indicated in the source (电影 film, 京剧 Peking opera, etc.).
- **Showtime** — daytime or evening show.
- **Advertising label** — extra promotional text from the source
  (e.g. 进口片, a troupe name), variable in nature.
- **Source** — as above.

**Performer information**

- **Name of the performer** — recorded mainly for opera and drama actors listed
  by name in the advertisement.
- Each performer is linked to the performed item they appeared in.

> The full FileMaker database holds further fields not included in this online
> version — facility address, city, class, status, and controlling authority;
> performance initial and final dates; remarks; performer function and
> performer advertising text; and geocoding data. These are available on
> request at enpmuc[at]gmail.com.
        """
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
            color_discrete_sequence=["#a5d6a7"],  # light green fill
        )
        fig.update_traces(line_color="#66bb6a")
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
            title="Busiest venues",
            labels={"items": "Performed items", "venue": ""},
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
    name = st.text_input("Performer name (Chinese)", placeholder="e.g. 麒麟童",
                         key="perf_tab_search")
    if name:
        appearances = q(
            """
            SELECT pi.show_id AS show_id, s.date_iso AS date, s.venue AS venue,
                   pi.title AS title, pi.genre AS genre,
                   pi.show_time AS show_time
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
            st.caption("Click any appearance to reconstitute the full show.")
            perf_event = st.dataframe(
                appearances, width="stretch", hide_index=True,
                on_select="rerun", selection_mode="single-row",
                key="perf_appearances",
            )
            perf_sel = (
                perf_event.selection.rows
                if perf_event and perf_event.selection else []
            )
            if perf_sel:
                picked = appearances.iloc[perf_sel[0]]
                show_id = picked["show_id"]
                st.divider()
                st.subheader(
                    f"🎭 Full show featuring {name} — “{picked['title']}”"
                )
                meta = show_meta(show_id)
                if not meta.empty:
                    m = meta.iloc[0]
                    bits = []
                    if m["venue"]:
                        bits.append(f"**Venue:** {m['venue']}")
                    if m["date_iso"]:
                        bits.append(f"**Date:** {m['date_iso']}")
                    if m["ticket_price"]:
                        bits.append(f"**Ticket price:** {m['ticket_price']}")
                    if bits:
                        st.markdown("  ·  ".join(bits))
                    if m["source"]:
                        st.caption(f"Source: {m['source']}")
                bill = show_items(show_id)
                st.write(
                    f"This show (`{show_id}`) comprises **{len(bill)}** "
                    f"performed item(s):"
                )
                st.dataframe(bill, width="stretch", hide_index=True)

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
        SELECT pi.show_id AS show_id, s.date_iso AS date, s.venue AS venue,
               pi.title AS title, pi.genre AS genre, pi.show_time AS show_time,
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
    st.caption("Click any row to reconstitute its full show below.")
    event = st.dataframe(
        rows, width="stretch", hide_index=True,
        on_select="rerun", selection_mode="single-row", key="browse_table",
    )
    st.download_button(
        "⬇ Download these results (CSV)",
        rows.to_csv(index=False).encode("utf-8-sig"),
        file_name="shanghai_entertainment_query.csv",
        mime="text/csv",
    )

    # ---- "Show" reconstitution (the FileMaker "Show" button) ---------------
    selected = event.selection.rows if event and event.selection else []
    if selected:
        picked = rows.iloc[selected[0]]
        show_id = picked["show_id"]
        st.divider()
        st.subheader(f"🎭 Full show for “{picked['title']}”")
        meta = show_meta(show_id)
        if not meta.empty:
            m = meta.iloc[0]
            bits = []
            if m["venue"]:
                bits.append(f"**Venue:** {m['venue']}")
            if m["date_iso"]:
                bits.append(f"**Date:** {m['date_iso']}")
            if m["ticket_price"]:
                bits.append(f"**Ticket price:** {m['ticket_price']}")
            if bits:
                st.markdown("  ·  ".join(bits))
            if m["source"]:
                st.caption(f"Source: {m['source']}")
        bill = show_items(show_id)
        st.write(
            f"This show (`{show_id}`) comprises **{len(bill)}** "
            f"performed item(s):"
        )
        st.dataframe(bill, width="stretch", hide_index=True)
