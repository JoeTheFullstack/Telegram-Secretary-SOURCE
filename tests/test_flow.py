import json
import unittest
from datetime import datetime, timedelta, timezone

from app.adapters.llm import LLMError, OfflineLLM, extract_json_object
from app.config import MIGRATIONS_DIR
from app.core import sessions
from app.core.router import Router
from app.domain.schemas import CustomerDraft, find_phone, normalize_phone
from app.infra.db import connect
from app.infra.migrations import run_migrations

OWNER, STAFF, CUSTOMER = 100, 200, 300


class ScriptedLLM:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def chat_json(self, system, user):
        self.calls.append(user)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def make_db():
    conn = connect(":memory:")
    run_migrations(conn, MIGRATIONS_DIR)
    return conn


def say(router, tid, text):
    return router.handle(tid, f"u{tid}", text)


def texts(replies):
    return "\n".join(r.text for r in replies)


class SchemaTests(unittest.TestCase):
    def test_phone_normalization(self):
        self.assertEqual(normalize_phone("۰۹۱۲۳۴۵۶۷۸۹"), "09123456789")
        self.assertEqual(normalize_phone("+98 912 345 6789"), "09123456789")
        self.assertEqual(normalize_phone("9123456789"), "09123456789")
        self.assertIsNone(normalize_phone("123"))
        self.assertIsNone(normalize_phone(None))

    def test_find_phone_in_text(self):
        self.assertEqual(find_phone("علی رضایی ۰۹۱۲-۳۴۵-۶۷۸۹ بودجه ۱۰ میلیارد"), "09123456789")
        self.assertIsNone(find_phone("بودجه ۱۰ میلیارد"))

    def test_from_raw_rejects_garbage_and_unknown_keys(self):
        d = CustomerDraft.from_raw({"full_name": "A1", "phone": "abc", "budget_max": "-5",
                                    "property_type": "castle", "role": "owner"})
        self.assertTrue(d.is_empty())
        d = CustomerDraft.from_raw({"full_name": " علی   رضایی ", "budget_max": "۱۰۰۰۰", "property_type": "LAND"})
        self.assertEqual((d.full_name, d.budget_max, d.property_type), ("علی رضایی", 10000, "land"))

    def test_extract_json_object(self):
        self.assertEqual(extract_json_object('here:\n```json\n{"a": 1}\n```'), {"a": 1})
        with self.assertRaises(LLMError):
            extract_json_object("no json")


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()

    def router(self, llm):
        return Router(self.conn, llm, owner_ids=[OWNER])

    def count(self, table):
        return self.conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]

    def test_customer_role_is_denied(self):
        r = self.router(OfflineLLM())
        out = say(r, CUSTOMER, "/newcustomer علی رضایی 09123456789")
        self.assertIn("اجازه", texts(out))
        self.assertEqual(self.count("customers"), 0)

    def test_llm_flow_end_to_end(self):
        llm = ScriptedLLM({"full_name": "علی رضایی", "phone": "09999999999",   # hallucinated phone
                           "budget_max": 10_000_000_000, "preferred_location": "شمال",
                           "property_type": "land", "role": "owner"})
        r = self.router(llm)
        out = say(r, OWNER, "مشتری جدید علی رضایی ۰۹۱۲۳۴۵۶۷۸۹ بودجه ۱۰ میلیارد زمین شمال")
        self.assertIn("10 میلیارد", texts(out))
        self.assertTrue(out[0].buttons)
        self.assertEqual(self.count("customers"), 0)           # nothing saved before confirm
        out = say(r, OWNER, "confirm")
        self.assertIn("ثبت شد", texts(out))
        row = self.conn.execute("SELECT * FROM customers").fetchone()
        self.assertEqual(row["phone"], "09123456789")           # phone came from text, not LLM
        self.assertEqual((row["budget_max"], row["property_type"]), (10_000_000_000, "land"))
        self.assertEqual(self.count("audit_logs"), 1)
        self.assertEqual(self.count("sessions"), 0)

    def test_offline_fallback_step_by_step(self):
        r = self.router(OfflineLLM())
        self.assertIn("نام", texts(say(r, OWNER, "/newcustomer")))
        self.assertIn("موبایل", texts(say(r, OWNER, "علی رضایی")))
        self.assertIn("معتبر نیست", texts(say(r, OWNER, "123")))
        self.assertIn("مشخصات", texts(say(r, OWNER, "۰۹۱۲۳۴۵۶۷۸۹")))
        say(r, OWNER, "تأیید")
        self.assertEqual(self.count("customers"), 1)

    def test_session_survives_restart(self):
        say(self.router(OfflineLLM()), OWNER, "/newcustomer")
        say(self.router(OfflineLLM()), OWNER, "علی رضایی")
        again = self.router(OfflineLLM())                        # new Router = "restart"
        out = say(again, OWNER, "09123456789")
        self.assertIn("مشخصات", texts(out))

    def test_session_expires(self):
        r = self.router(OfflineLLM())
        say(r, OWNER, "/newcustomer")
        old = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
        self.conn.execute("UPDATE sessions SET updated_at = ?", (old,))
        out = say(r, OWNER, "علی رضایی")                          # no longer treated as a name
        self.assertNotIn("موبایل", texts(out))
        self.assertEqual(self.count("sessions"), 0)

    def test_duplicate_phone_rejected(self):
        r = self.router(OfflineLLM())
        for _ in range(2):
            say(r, OWNER, "/newcustomer")
            say(r, OWNER, "علی رضایی")
            say(r, OWNER, "09123456789")
            out = say(r, OWNER, "confirm")
        self.assertIn("قبلاً", texts(out))
        self.assertEqual(self.count("customers"), 1)

    def test_unknown_command_is_not_swallowed_by_flow(self):
        r = self.router(OfflineLLM())
        say(r, OWNER, "/newcustomer")
        say(r, OWNER, "/whatever")
        self.assertIn("موبایل", texts(say(r, OWNER, "علی رضایی")))   # still asking for the name

    def test_cancel(self):
        r = self.router(OfflineLLM())
        say(r, OWNER, "/newcustomer")
        say(r, OWNER, "cancel")
        self.assertEqual(self.count("sessions"), 0)

    def test_setrole_owner_only_and_audited(self):
        r = self.router(OfflineLLM())
        self.assertIn("اجازه", texts(say(r, STAFF, "/setrole 200 manager")))
        say(r, OWNER, f"/setrole {STAFF} staff")
        say(r, STAFF, "/newcustomer")                            # now allowed
        self.assertIn("نام", texts(say(r, STAFF, "/newcustomer")))
        self.assertIn("اجازه", texts(say(r, STAFF, "/setrole 200 owner")))
        self.assertEqual(self.count("audit_logs"), 1)

    def test_owner_role_comes_from_config_not_db_hack(self):
        r = self.router(OfflineLLM())
        say(r, OWNER, "/myid")
        self.conn.execute("UPDATE users SET role = 'customer' WHERE telegram_id = ?", (OWNER,))
        self.assertNotIn("اجازه", texts(say(r, OWNER, "/newcustomer")))

    def test_migrations_are_idempotent(self):
        self.assertEqual(run_migrations(self.conn, MIGRATIONS_DIR), [])


if __name__ == "__main__":
    unittest.main()
