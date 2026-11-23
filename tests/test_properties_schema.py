import sqlite3
import unittest

from app.config import MIGRATIONS_DIR
from app.infra.db import connect
from app.infra.migrations import run_migrations


def make_db():
    conn = connect(":memory:")
    run_migrations(conn, MIGRATIONS_DIR)
    conn.execute("INSERT INTO users(telegram_id, display_name, role) VALUES (1, 'u', 'staff')")
    return conn


def add_property(conn, **over):
    values = {"title": "زمین ۵۰۰ متری، شمال", "property_type": "land", "area_m2": 500,
              "location": "شمال", "price": 10_000_000_000, "created_by": 1}
    values.update(over)
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    cur = conn.execute("INSERT INTO properties(%s) VALUES (%s)" % (cols, marks), tuple(values.values()))
    return cur.lastrowid


class PropertySchemaTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()

    def tearDown(self):
        self.conn.close()

    def test_tables_exist_and_status_defaults_to_available(self):
        pid = add_property(self.conn)
        row = self.conn.execute("SELECT status FROM properties WHERE id = ?", (pid,)).fetchone()
        self.assertEqual(row["status"], "available")

    def test_bad_values_are_rejected(self):
        for bad in ({"property_type": "castle"}, {"status": "gone"}, {"area_m2": 0},
                    {"price": -5}, {"location": None}, {"created_by": 999}):
            with self.assertRaises(sqlite3.IntegrityError, msg=str(bad)):
                add_property(self.conn, **bad)

    def test_media_is_linked_and_duplicates_are_rejected(self):
        pid = add_property(self.conn)
        sql = ("INSERT INTO property_media(property_id, kind, file_id, file_unique_id, added_by) "
               "VALUES (?, ?, ?, ?, 1)")
        self.conn.execute(sql, (pid, "photo", "FILEID1", "UNIQ1"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(sql, (pid, "photo", "FILEID1b", "UNIQ1"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(sql, (pid, "gif", "FILEID2", "UNIQ2"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(sql, (12345, "photo", "FILEID3", "UNIQ3"))

    def test_deleting_a_property_deletes_its_media(self):
        pid = add_property(self.conn)
        self.conn.execute(
            "INSERT INTO property_media(property_id, kind, file_id, file_unique_id, added_by) "
            "VALUES (?, 'video', 'F', 'U', 1)", (pid,))
        self.conn.execute("DELETE FROM properties WHERE id = ?", (pid,))
        count = self.conn.execute("SELECT COUNT(*) AS c FROM property_media").fetchone()["c"]
        self.assertEqual(count, 0)

    def test_migration_002_is_recorded(self):
        versions = [r["version"] for r in self.conn.execute("SELECT version FROM schema_migrations")]
        self.assertIn("002_properties", versions)


if __name__ == "__main__":
    unittest.main()
