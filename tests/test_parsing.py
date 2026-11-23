import unittest

from app.domain.parsing import apply_text_rules, find_budget, find_property_type, find_region
from app.domain.schemas import CustomerDraft

B = 10 ** 9
M = 10 ** 6


class BudgetTests(unittest.TestCase):
    def test_single_amount_is_max(self):
        self.assertEqual(find_budget("بودجه 10 میلیارد"), (None, 10 * B))

    def test_range_with_shared_unit(self):
        self.assertEqual(find_budget("بودجه 5 تا 10 میلیارد"), (5 * B, 10 * B))

    def test_range_with_two_units(self):
        self.assertEqual(find_budget("500 میلیون تا 2 میلیارد"), (500 * M, 2 * B))

    def test_decimals(self):
        self.assertEqual(find_budget("2.5 میلیارد"), (None, 2500 * M))
        self.assertEqual(find_budget("2/5 میلیارد"), (None, 2500 * M))

    def test_number_words(self):
        self.assertEqual(find_budget("ده میلیارد"), (None, 10 * B))
        self.assertEqual(find_budget("دو و نیم میلیارد"), (None, 2500 * M))
        self.assertEqual(find_budget("پنجاه میلیون"), (None, 50 * M))

    def test_at_least(self):
        self.assertEqual(find_budget("حداقل 3 میلیارد"), (3 * B, None))

    def test_plain_big_number(self):
        self.assertEqual(find_budget("10,000,000,000 تومان"), (None, 10 * B))
        self.assertEqual(find_budget("500000000 تومان"), (None, 500 * M))

    def test_no_false_positives(self):
        self.assertEqual(find_budget("زمین 500 متری"), (None, None))
        self.assertEqual(find_budget("علی رضایی"), (None, None))


class TypeAndRegionTests(unittest.TestCase):
    def test_property_types(self):
        for text, kind in (("زمین شمال", "land"), ("آپارتمان در تهران", "apartment"),
                           ("ویلایی", "villa"), ("مغازه", "commercial"), ("باغ", "garden")):
            self.assertEqual(find_property_type(text)[0], kind, text)
        self.assertIsNone(find_property_type("علی رضایی")[0])

    def test_surname_is_not_a_type(self):
        self.assertIsNone(find_property_type("علی باغی")[0])

    def test_region_after_type(self):
        t = "بودجه 10 میلیارد زمین شمال"
        self.assertEqual(find_region(t, find_property_type(t)[1]), "شمال")

    def test_region_with_filler_and_stop(self):
        t = "آپارتمان در سعادت آباد برای سرمایه"
        self.assertEqual(find_region(t, find_property_type(t)[1]), "سعادت آباد")

    def test_explicit_region_markers(self):
        self.assertEqual(find_region("منطقه شمال", 0), "شمال")
        self.assertEqual(find_region("منطقه 5", 0), "منطقه 5")


class ApplyRulesTests(unittest.TestCase):
    TEXT = "علی رضایی ۰۹۱۲۳۴۵۶۷۸۹ بودجه ۱۰ میلیارد زمین شمال"

    def test_fixes_what_the_small_model_got_wrong(self):
        # the exact wrong answer qwen2.5:1.5b gave on the real machine
        wrong = CustomerDraft(full_name="علی رضایی", budget_max=1 * B,
                              preferred_location="زمین", property_type="land")
        d = apply_text_rules(wrong, self.TEXT)
        self.assertEqual((d.full_name, d.budget_min, d.budget_max, d.preferred_location, d.property_type),
                         ("علی رضایی", None, 10 * B, "شمال", "land"))

    def test_works_without_any_llm_help(self):
        d = apply_text_rules(CustomerDraft(), self.TEXT)
        self.assertEqual((d.full_name, d.budget_max, d.preferred_location, d.property_type),
                         ("علی رضایی", 10 * B, "شمال", "land"))

    def test_phone_digits_are_not_a_budget(self):
        d = apply_text_rules(CustomerDraft(), "علی رضایی 09123456789")
        self.assertEqual((d.budget_min, d.budget_max), (None, None))

    def test_invented_values_are_dropped(self):
        llm = CustomerDraft(full_name="Reza Karimi", budget_max=5 * B, preferred_location="کیش")
        d = apply_text_rules(llm, "علی رضایی 09123456789")
        self.assertEqual((d.budget_max, d.preferred_location), (None, None))
        self.assertEqual(d.full_name, "علی رضایی")

    def test_good_llm_values_are_kept(self):
        llm = CustomerDraft(full_name="مریم احمدی", budget_min=2 * B, budget_max=3 * B,
                            preferred_location="سعادت آباد")
        d = apply_text_rules(llm, "مریم احمدی بودجه 2 تا 3 میلیارد دنبال سعادت آباد")
        self.assertEqual((d.full_name, d.budget_min, d.budget_max, d.preferred_location),
                         ("مریم احمدی", 2 * B, 3 * B, "سعادت آباد"))


if __name__ == "__main__":
    unittest.main()
