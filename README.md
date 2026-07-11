# Shanghai Entertainment Dashboard

An interactive [Streamlit](https://streamlit.io) dashboard for exploring the
**Leisure_ALL** historical database of Shanghai theatre, opera, and cinema
programmes (**1907–1991**), reconstructed from a FileMaker export.

The source data was transcribed from period newspapers (*申报 Shenbao*,
*新闻报 Xinwenbao*, …) and covers tens of thousands of shows across the great
Shanghai amusement halls (大世界, 先施乐园, 新世界 …), theatres, and cinemas.

![overview](docs/screenshot.png)

## What's inside

The dashboard lets you:

- see performed items per year across the whole period;
- break activity down by **genre** (电影 film, 京剧 Peking opera, 越剧 Yue opera,
  话剧 spoken drama, 滑稽 comedy, …) and track genre trends over time;
- rank and inspect the **busiest venues**;
- **search a performer** (e.g. 麒麟童) to see every billed appearance and a
  per-year timeline;
- **browse and full-text search** performed items, filter by year/genre/venue,
  and export the current selection to CSV.

## Data model

The FileMaker export is reshaped into three linked tables in a SQLite database:

```
shows ──show_id──< performed_items ──item_id──< performers
```

| Table | Rows | Key columns |
|-------|------|-------------|
| `shows` | ~85,500 | `show_id`, `date_iso`, `year`, `venue`, `ticket_price`, `source` |
| `performed_items` | ~138,700 | `item_id`, `show_id`, `title`, `genre`, `advertising_label`, `show_time`, `source` |
| `performers` | ~81,300 | `item_id`, `performer_name`, `performer_id` |

## Quick start

```bash
# 1. install dependencies
pip install -r requirements.txt

# 2. (optional) rebuild the database from the raw exports
#    Needs data/raw/*.csv present. On cloud-synced folders (Dropbox/iCloud),
#    build to local disk first to avoid SQLite "disk I/O error":
python scripts/data_prep.py
#    or:  SE_DB_PATH=/tmp/se.db python scripts/data_prep.py && cp /tmp/se.db data/shanghai_entertainment.db

# 3. run the dashboard
streamlit run app.py
```

The prebuilt database (`data/shanghai_entertainment.db`) is included, so step 2
is only needed if you re-export the FileMaker source.

## The raw exports (notes for rebuilding)

The original CSVs are quirky FileMaker exports, handled by
`scripts/data_prep.py`:

- **records are separated by carriage returns** (`\r`, old-Mac style), not
  newlines — most tools read the whole file as one line unless you account for
  this;
- **in-cell line breaks are vertical tabs** (`0x0B`), converted to `\n`;
- there are **no header rows**; column order follows the FileMaker export
  layout and was mapped against the DDR (`Leisure_ALL_fmp12.xml`);
- `Performers.csv` and `Performers_List.csv` are identical duplicates;
- dates are stored as `YYYY=MM=DD` and normalized to ISO `YYYY-MM-DD`.

Raw exports live under `data/raw/` and are **git-ignored** (large, and the DB
is derived from them).

## Deploy

Push to GitHub and deploy free on
[Streamlit Community Cloud](https://streamlit.io/cloud): point it at `app.py`.
The committed SQLite DB (~38 MB) ships with the repo, so no build step is
needed at deploy time.

## Caveats

Coverage reflects surviving newspaper sources, so gaps and spikes are partly
archival artefacts rather than real shifts in activity. Titles, venue names,
and performer names retain their original Chinese orthography.

## License

Code released under the MIT License (see `LICENSE`). The underlying historical
data belongs to its original compilers; check with them before redistributing.
