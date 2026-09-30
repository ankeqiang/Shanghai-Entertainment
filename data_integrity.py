"""Conservative corrections and performer-link validation for the export."""

PUBLISHED_ITEM_COUNT = 139_655


def corrected_show_date(show_id, date_iso, year, source):
    """Correct only two confirmed transpositions, with source evidence."""
    if (
        show_id in {"00101007", "00101008"}
        and date_iso == "1991-08-02"
        and year == 1991
        and source.startswith("申报, 1919=08=02,")
    ):
        return "1919-08-02", 1919
    return date_iso, year


def create_performer_view(connection):
    """Keep links to exactly one item without changing source tables.

    Repeated item identifiers and orphan links cannot be assigned reliably.
    This establishes unambiguous joins, not verified historical identities.
    A temporary view also works with a read-only, immutable database.
    """
    connection.execute(
        """
        CREATE TEMP VIEW IF NOT EXISTS unambiguous_performers AS
        SELECT pf.* FROM performers pf
        JOIN (
            SELECT item_id FROM performed_items
            GROUP BY item_id HAVING COUNT(*) = 1
        ) unique_items ON unique_items.item_id = pf.item_id
        """
    )
