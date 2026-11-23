import unittest

from app.adapters.llm import OfflineLLM
from app.core.router import Router
from app.domain.property_parsing import find_area, parse_awaited, parse_property_text
from tests.test_flow import CUSTOMER, OWNER, make_db, say, texts

STAFF = 200
B = 10 ** 9


class PropertyParsingTests(unittest.TestCase):
    def test_full_description(self):
        d = parse_property_text("زمین 500 متری شمال 10 میلیارد")
        self.assertEqual((d.property_type, d.area_m2, d.location, d.price), ("land", 500, "شمال", 10 * B))

    def test_persian_digits_and_two_word_region(self):
        d = parse_property_text("ویلا ۳۰۰ متر سعادت آباد ۲۵ میلیارد")
        self.assertEqual((d.property_type, d.area_m2, d.location, d.price), ("villa", 300, "سعادت آباد", 25 * B))

    def test_noise_words_and_filler(self):
        d = parse_property_text("آپارتمان در منطقه 5 متراژ 85 قیمت 3.5 میلیارد")
        self.assertEqual((d.property_type, d.area_m2, d.location, d.price), ("apartment", 85, "منطقه 5", 3500000000))

    def test_number_words(self):
        self.assertEqual(parse_property_text("باغ 1000 متری لواسان ده میلیارد").price, 10 * B)

    def test_phone_is_never_a_price(self):
        self.assertIsNone(parse_property_text("زمین شمال 09123456789").price)

    def test_area_variants(self):
        self.assertEqual(find_area("500 متر")[0], 500)
        self.assertEqual(find_area("120 متر مربع")[0], 120)
        self.assertEqual(find_area("متراژ 75")[0], 75)
        self.assertIsNone(find_area("10 میلیارد")[0])

    def test_awaited_answers(self):
        self.assertEqual(parse_awaited("area_m2", "500").area_m2, 500)
        self.assertEqual(parse_awaited("price", "850 میلیون").price, 850 * 10 ** 6)
        self.assertTrue(parse_awaited("price", "10").is_empty())       # no unit -> ask again
        self.assertTrue(parse_awaited("property_type", "قصر").is_empty())
        self.assertTrue(parse_awaited("location", "سلام").is_empty())
        self.assertTrue(parse_awaited("location", "زمین").is_empty())
        self.assertEqual(parse_awaited("location", "سعادت آباد").location, "سعادت آباد")


class PropertyFlowTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()
        self.r = Router(self.conn, OfflineLLM(), owner_ids=[OWNER])
        say(self.r, OWNER, "/setrole %d staff" % STAFF)

    def tearDown(self):
        self.conn.close()

    def test_one_message_flow_saves_property_and_audit(self):
        out = say(self.r, STAFF, "ملک جدید زمین 500 متری شمال 10 میلیارد")
        self.assertIn("زمین 500 متری، شمال", texts(out))
        self.assertTrue(out[0].buttons)
        out = say(self.r, STAFF, "confirm")
        self.assertIn("ملک ثبت شد", texts(out))
        row = self.conn.execute("SELECT * FROM properties").fetchone()
        self.assertEqual((row["title"], row["property_type"], row["area_m2"], row["location"], row["price"],
                          row["status"]), ("زمین 500 متری، شمال", "land", 500, "شمال", 10 * B, "available"))
        n = self.conn.execute("SELECT COUNT(*) AS c FROM audit_logs WHERE action = 'property.create'").fetchone()["c"]
        self.assertEqual(n, 1)

    def test_asks_only_for_missing_fields_in_order(self):
        self.assertIn("متراژ", texts(say(self.r, STAFF, "ملک جدید زمین شمال 10 میلیارد")))
        self.assertIn("متراژ", texts(say(self.r, STAFF, "سلام")))          # junk -> asked again
        self.assertIn("مشخصات ملک", texts(say(self.r, STAFF, "500")))

    def test_empty_start_asks_everything_step_by_step(self):
        self.assertIn("نوع ملک", texts(say(self.r, STAFF, "/newproperty")))
        self.assertIn("منطقه", texts(say(self.r, STAFF, "ویلا")))
        self.assertIn("متراژ", texts(say(self.r, STAFF, "لواسان")))
        self.assertIn("قیمت", texts(say(self.r, STAFF, "300")))
        self.assertIn("مشخصات ملک", texts(say(self.r, STAFF, "25 میلیارد")))

    def test_correction_at_confirm_step(self):
        say(self.r, STAFF, "ملک جدید زمین 500 متری شمال 10 میلیارد")
        out = say(self.r, STAFF, "قیمت 12 میلیارد")
        self.assertIn("12 میلیارد", texts(out))
        say(self.r, STAFF, "confirm")
        self.assertEqual(self.conn.execute("SELECT price FROM properties").fetchone()["price"], 12 * B)

    def test_old_confirm_button_does_not_save(self):
        say(self.r, STAFF, "ملک جدید زمین شمال")                          # now asking for the area
        out = say(self.r, STAFF, "confirm")
        self.assertIn("متراژ", texts(out))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) AS c FROM properties").fetchone()["c"], 0)

    def test_customer_role_is_denied(self):
        self.assertIn("اجازه", texts(say(self.r, CUSTOMER, "ملک جدید زمین 500 متری شمال 10 میلیارد")))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) AS c FROM properties").fetchone()["c"], 0)

    def test_cancel_clears_property_flow(self):
        say(self.r, STAFF, "/newproperty")
        say(self.r, STAFF, "لغو")
        self.assertNotIn("نوع ملک", texts(say(self.r, STAFF, "زمین")))


    def test_media_upload_flow_saves_photo_and_video_then_done(self):
        say(self.r, STAFF, "ملک جدید زمین 500 متری شمال 10 میلیارد")
        out = say(self.r, STAFF, "confirm")
        self.assertIn("عکس‌ها و فیلم‌ها", texts(out))
        self.assertEqual(self.conn.execute("SELECT flow FROM sessions").fetchone()["flow"], "property_media")

        photo = {"kind": "photo", "file_id": "PHOTO_FILE", "file_unique_id": "PHOTO_UNIQUE",
                 "media_group_id": "ALBUM_1", "caption": "نمای ساختمان"}
        out = self.r.handle(STAFF, "staff", "نمای ساختمان", photo)
        self.assertIn("عکس", texts(out))
        video = {"kind": "video", "file_id": "VIDEO_FILE", "file_unique_id": "VIDEO_UNIQUE",
                 "media_group_id": None, "caption": ""}
        out = self.r.handle(STAFF, "staff", "", video)
        self.assertIn("ویدئو", texts(out))

        rows = self.conn.execute(
            "SELECT kind, file_id, file_unique_id, media_group_id, caption FROM property_media ORDER BY id"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(tuple(rows[0]), ("photo", "PHOTO_FILE", "PHOTO_UNIQUE", "ALBUM_1", "نمای ساختمان"))
        self.assertEqual(tuple(rows[1]), ("video", "VIDEO_FILE", "VIDEO_UNIQUE", None, None))
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) c FROM audit_logs WHERE action='property.media.add'"
        ).fetchone()["c"], 2)

        out = say(self.r, STAFF, "/done")
        self.assertIn("تعداد رسانه‌های ثبت‌شده: 2", texts(out))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"], 0)

    def test_duplicate_media_is_not_inserted_twice(self):
        say(self.r, STAFF, "ملک جدید زمین 500 متری شمال 10 میلیارد")
        say(self.r, STAFF, "confirm")
        media = {"kind": "photo", "file_id": "F1", "file_unique_id": "U1"}
        self.r.handle(STAFF, "staff", "", media)
        out = self.r.handle(STAFF, "staff", "", media)
        self.assertIn("قبلاً", texts(out))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM property_media").fetchone()["c"], 1)

    def test_cancel_media_collection_does_not_delete_property(self):
        say(self.r, STAFF, "ملک جدید زمین 500 متری شمال 10 میلیارد")
        say(self.r, STAFF, "confirm")
        out = say(self.r, STAFF, "/cancel")
        self.assertIn("خود ملک ثبت‌شده حذف نمی‌شود", texts(out))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM properties").fetchone()["c"], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"], 0)

    def test_customer_cannot_upload_media(self):
        media = {"kind": "photo", "file_id": "F", "file_unique_id": "U"}
        out = self.r.handle(CUSTOMER, "customer", "", media)
        self.assertIn("اجازه", texts(out))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM property_media").fetchone()["c"], 0)

    def test_addmedia_reopens_existing_property_and_appends_media(self):
        say(self.r, STAFF, "ملک جدید زمین 500 متری شمال 10 میلیارد")
        say(self.r, STAFF, "confirm")
        first = {"kind": "photo", "file_id": "OLD_FILE", "file_unique_id": "OLD_UNIQUE"}
        self.r.handle(STAFF, "staff", "", first)
        say(self.r, STAFF, "/done")

        out = say(self.r, STAFF, "/addmedia 1")
        self.assertIn("افزودن رسانه برای ملک 1 فعال شد", texts(out))
        new = {"kind": "video", "file_id": "NEW_VIDEO", "file_unique_id": "NEW_VIDEO_UNIQUE"}
        out = self.r.handle(STAFF, "staff", "", new)
        self.assertIn("ویدئو", texts(out))
        out = say(self.r, STAFF, "/done")
        self.assertIn("تعداد رسانه‌های ثبت‌شده: 2", texts(out))
        rows = self.conn.execute(
            "SELECT kind,file_id FROM property_media WHERE property_id=1 ORDER BY id"
        ).fetchall()
        self.assertEqual([tuple(row) for row in rows], [("photo", "OLD_FILE"), ("video", "NEW_VIDEO")])

    def test_addmedia_requires_property_id(self):
        out = say(self.r, STAFF, "/addmedia")
        self.assertIn("فرمت دستور", texts(out))

    def test_addmedia_rejects_unknown_property(self):
        out = say(self.r, STAFF, "/addmedia 999")
        self.assertIn("پیدا نشد", texts(out))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)

    def test_customer_cannot_use_addmedia(self):
        out = say(self.r, CUSTOMER, "/addmedia 1")
        self.assertIn("اجازه", texts(out))

    def test_addmedia_does_not_replace_an_active_flow(self):
        say(self.r, STAFF, "/newproperty")
        out = say(self.r, STAFF, "/addmedia 1")
        self.assertIn("یک عملیات دیگر هنوز فعال است", texts(out))
        self.assertEqual(self.conn.execute("SELECT flow FROM sessions").fetchone()[0], "new_property")

    def test_customer_flow_still_works(self):
        out = say(self.r, STAFF, "مشتری جدید علی رضایی 09123456789 بودجه 10 میلیارد زمین شمال")
        self.assertIn("مشخصات مشتری", texts(out))


if __name__ == "__main__":
    unittest.main()
