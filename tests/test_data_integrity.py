"""Regression checks using the app's actual queries and small source fixtures."""

import ast
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data_integrity import corrected_show_date, create_performer_view


class DateCorrections(unittest.TestCase):
    def test_confirmed_transpositions(self):
        for show_id in ("00101007", "00101008"):
            self.assertEqual(
                corrected_show_date(show_id, "1991-08-02", 1991,
                                    "申报, 1919=08=02, 5, 2/#4"),
                ("1919-08-02", 1919),
            )

    def test_requires_matching_record_date_and_source(self):
        cases = [
            ("other", "1991-08-02", 1991, "申报, 1919=08=02, 5"),
            ("00101007", "1991-08-02", 1991, "unrelated"),
            ("00101007", "1919-08-02", 1919, "申报, 1919=08=02, 5"),
            ("00101007", None, None, "申报, 1919=08=02, 5"),
        ]
        for show_id, date, year, source in cases:
            self.assertEqual(corrected_show_date(show_id, date, year, source),
                             (date, year))


class PerformerLinks(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.addCleanup(self.con.close)
        self.con.executescript("""
            CREATE TABLE shows(show_id TEXT, year INTEGER, date_iso TEXT, venue TEXT);
            CREATE TABLE performed_items(row_id INTEGER, item_id TEXT, show_id TEXT,
                                         title TEXT, genre TEXT, show_time TEXT);
            CREATE TABLE performers(row_id INTEGER, item_id TEXT, performer_name TEXT);
            INSERT INTO shows VALUES
                ('a',1919,'1919-08-02','Hall A'),
                ('b',1931,'1931-10-10','Hall B');
            INSERT INTO performed_items VALUES
                (1,'unique-a','a','Early','opera','Daytime show'),
                (2,'unique-b','b','Later','film','Evening show'),
                (3,'collision','a','Other early','opera','Daytime show'),
                (4,'collision','b','Other late','film','Evening show');
            INSERT INTO performers VALUES
                (1,'unique-a','Actor'),(2,'unique-b','Actor'),
                (3,'collision','Ambiguous'),(4,'missing','Orphan');
        """)
        create_performer_view(self.con)

    def test_ambiguous_and_orphan_links_excluded_without_deletion(self):
        self.assertEqual(self.con.execute(
            'SELECT row_id FROM unambiguous_performers ORDER BY row_id'
        ).fetchall(), [(1,), (2,)])
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM performers').fetchone()[0], 4)
        create_performer_view(self.con)  # Safe to initialize again.

    def test_app_exact_search_respects_each_sidebar_filter(self):
        tree = ast.parse((ROOT / 'app.py').read_text())
        func = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == 'where_clause')
        env = {}
        exec(compile(ast.Module(body=[func], type_ignores=[]), 'app.py', 'exec'), env)
        call = next(n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'appearances'
                            for t in n.targets))
        cases = [
            (((1907,1966), [], [], ''), ['Early','Later']),
            (((1919,1919), [], [], ''), ['Early']),
            (((1907,1966), ['film'], [], ''), ['Later']),
            (((1907,1966), [], ['Hall B'], ''), ['Later']),
            (((1907,1966), [], [], 'Ambiguous'), []),
        ]
        for filters, titles in cases:
            where, params = env['where_clause'](*filters)
            scope = {'WHERE': where, 'PARAMS': params, 'name': 'Actor'}
            sql = eval(compile(ast.Expression(call.args[0]), 'app.py', 'eval'), scope)
            args = eval(compile(ast.Expression(call.args[1]), 'app.py', 'eval'), scope)
            self.assertEqual([r[3] for r in self.con.execute(sql, args)], titles)

    def test_read_only_database_supports_temporary_view(self):
        path = ROOT / 'data' / 'shanghai_entertainment.db'
        con = sqlite3.connect(f'file:{path}?mode=ro&immutable=1', uri=True)
        self.addCleanup(con.close)
        create_performer_view(con)
        invalid = con.execute("""
            SELECT COUNT(*) FROM unambiguous_performers pf
            WHERE (SELECT COUNT(*) FROM performed_items pi
                   WHERE pi.item_id=pf.item_id) <> 1
        """).fetchone()[0]
        self.assertEqual(invalid, 0)


if __name__ == '__main__':
    unittest.main()
