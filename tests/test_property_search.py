import unittest
from unittest.mock import patch

from app.adapters.llm import OfflineLLM
from app.adapters.telegram import TelegramClient
from app.core import sessions
from app.core.router import Router
from app.core.sessions import Session
from app.repositories.users import get_by_telegram_id
from tests.test_flow import CUSTOMER, OWNER, make_db, say, texts

STAFF = 200
BASE = 10 ** 9


class PropertySearchTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()
        self.router = Router(self.conn, OfflineLLM(), owner_ids=[OWNER])
        say(self.router, OWNER, f"/setrole {STAFF} staff")
        self._create("زمین 500 متری شمال 10 میلیارد")
        self._create("ویلا 300 متری لواسان 25 میلیارد")
        self._create("آپارتمان 100 متری تهران 5 میلیارد")

    def tearDown(self):
        self.conn.close()

    def _create(self, description):
        say(self.router, STAFF, "ملک جدید " + description)
        say(self.router, STAFF, "confirm")
        say(self.router, STAFF, "/done")

    def test_customer_search_only_shows_available_and_detail_media(self):
        # Mark the second property reserved; a customer must not discover it.
        self.conn.execute("UPDATE properties SET status='reserved' WHERE id=2")
        staff = get_by_telegram_id(self.conn, STAFF)
        media = {"kind": "photo", "file_id": "PHOTO_1", "file_unique_id": "UNIQUE_1"}
        from app.services.property_service import add_property_media
        add_property_media(self.conn, staff, 1, media)

        out = say(self.router, CUSTOMER, "/search")
        self.assertIn("2 ملک", texts(out))
        self.assertIn("زمین 500 متری", texts(out))
        self.assertNotIn("ویلا 300 متری", texts(out))
        detail = self.router.handle(CUSTOMER, "customer", "pv:1")
        self.assertEqual(detail[0].media, None)
        self.assertEqual(detail[1].media["kind"], "photo")
        self.assertEqual(detail[1].media["file_id"], "PHOTO_1")
        self.assertIsNone(self.router.handle(CUSTOMER, "customer", "pv:2")[0].media)
        self.assertIn("در دسترس نیست", texts(self.router.handle(CUSTOMER, "customer", "pv:2")))

    def test_staff_can_search_reserved_and_sold(self):
        self.conn.execute("UPDATE properties SET status='sold' WHERE id=1")
        out = say(self.router, STAFF, "/search")
        self.assertIn("3 ملک", texts(out))
        self.assertIn("فروخته‌شده", texts(out))

    def test_search_filters_type_location_area_and_price(self):
        out = say(self.router, CUSTOMER, "/search زمین شمال 400 متر 12 میلیارد")
        self.assertIn("زمین 500 متری", texts(out))
        self.assertNotIn("ویلا", texts(out))
        self.assertNotIn("آپارتمان", texts(out))

    def test_search_does_not_overwrite_active_registration_session(self):
        say(self.router, STAFF, "/newproperty")
        before = self.conn.execute("SELECT flow, awaiting, data FROM sessions").fetchone()
        out = say(self.router, STAFF, "/search")
        after = self.conn.execute("SELECT flow, awaiting, data FROM sessions").fetchone()
        self.assertIn("نتایج جست‌وجو", texts(out))
        self.assertEqual(tuple(before), tuple(after))
        self.assertEqual(after["flow"], "new_property")

    def test_pagination_and_empty_results(self):
        # Create enough properties for a second page.
        for i in range(3):
            self._create(f"زمین {600+i} متری کرج {2+i} میلیارد")
        out = say(self.router, CUSTOMER, "/search")
        self.assertIn("از 6 ملک", texts(out))
        out = say(self.router, CUSTOMER, "ps:next")
        self.assertIn("کد 1", texts(out))
        out = say(self.router, CUSTOMER, "ps:prev")
        self.assertIn("کد 6", texts(out))
        out = say(self.router, CUSTOMER, "/search شهر خیالی")
        self.assertIn("پیدا نشد", texts(out))

    def test_invalid_property_callback(self):
        self.assertIn("معتبر نیست", texts(self.router.handle(CUSTOMER, "customer", "pv:abc")))


class TelegramOutgoingMediaTests(unittest.TestCase):
    def test_send_media_uses_telegram_photo_and_video_methods(self):
        client = TelegramClient("TEST_TOKEN")
        with patch.object(client, "_call") as call:
            client.send_media(123, {"kind": "photo", "file_id": "PHOTO_ID", "caption": "Photo"})
            self.assertEqual(call.call_args[0][0], "sendPhoto")
            client.send_media(123, {"kind": "video", "file_id": "VIDEO_ID", "caption": "Video"})
            self.assertEqual(call.call_args[0][0], "sendVideo")


if __name__ == "__main__":
    unittest.main()
