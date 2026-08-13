import unittest
from datetime import date, timedelta

from pydantic import ValidationError

from app.agents.travel.planning import (
    build_alternatives,
    build_itinerary,
    calculate_budget,
    optimize_plan_for_budget,
)
from app.agents.travel.schemas import TripRequest


FUTURE_START = (date.today() + timedelta(days=60)).isoformat()
FUTURE_END = (date.today() + timedelta(days=61)).isoformat()


class TravelPlanningTests(unittest.TestCase):
    def test_required_fields_are_reported(self):
        request = TripRequest(destination="上海")
        self.assertEqual(
            request.missing_required(),
            ["出发日期", "返程日期", "出行人数"],
        )

    def test_invalid_date_range_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "返程日期"):
            TripRequest(
                destination="上海",
                start_date=FUTURE_END,
                end_date=FUTURE_START,
                travelers=2,
            )

    def test_itinerary_respects_daily_pace(self):
        request = {
            "destination": "上海",
            "start_date": FUTURE_START,
            "end_date": FUTURE_END,
            "pace": "relaxed",
        }
        attractions = [
            {
                "id": f"attraction-{i}",
                "name": f"景点{i}",
                "area": "黄浦区",
                "evidence": [{"source_url": f"https://e/{i}"}],
            }
            for i in range(4)
        ]
        itinerary = build_itinerary(request, attractions, {"forecast": []})
        self.assertEqual(len(itinerary), 2)
        self.assertTrue(all(len(day["activities"]) <= 2 for day in itinerary))

    def test_itinerary_does_not_mix_areas_to_fill_a_day(self):
        request = {
            "destination": "上海",
            "start_date": FUTURE_START,
            "end_date": FUTURE_END,
            "pace": "balanced",
        }
        attractions = [
            {
                "id": "a1", "name": "A", "area": "黄浦区",
                "evidence": [{"source_url": "https://e/a"}],
            },
            {
                "id": "a2", "name": "B", "area": "黄浦区",
                "evidence": [{"source_url": "https://e/b"}],
            },
            {
                "id": "a3", "name": "C", "area": "浦东新区",
                "evidence": [{"source_url": "https://e/c"}],
            },
        ]
        itinerary = build_itinerary(request, attractions, {"forecast": []})
        self.assertEqual(
            [[item["name"] for item in day["activities"]] for day in itinerary],
            [["A", "B"], ["C"]],
        )

    def test_unknown_locations_are_not_assumed_to_be_near_each_other(self):
        request = {
            "destination": "上海",
            "start_date": FUTURE_START,
            "end_date": FUTURE_END,
            "pace": "balanced",
        }
        attractions = [
            {"id": "a", "name": "未知地点A", "area": None, "evidence": []},
            {"id": "b", "name": "未知地点B", "area": None, "evidence": []},
        ]
        itinerary = build_itinerary(request, attractions, {"forecast": []})
        self.assertEqual(
            [len(day["activities"]) for day in itinerary],
            [1, 1],
        )
        self.assertTrue(
            all(day["geography_confidence"] == "unknown" for day in itinerary)
        )

    def test_candidate_is_not_scheduled_on_explicit_closure_weekday(self):
        next_monday = date.today() + timedelta(
            days=(7 - date.today().weekday()) % 7
        )
        if next_monday == date.today():
            next_monday += timedelta(days=7)
        request = {
            "destination": "上海",
            "start_date": next_monday.isoformat(),
            "end_date": next_monday.isoformat(),
            "pace": "balanced",
        }
        itinerary = build_itinerary(request, [{
            "id": "closed",
            "name": "周一闭馆博物馆",
            "area": "黄浦区",
            "opening_hours": "周一闭馆，周二至周日开放",
            "evidence": [],
        }], {"forecast": []})

        self.assertEqual(itinerary[0]["activities"], [])
        self.assertEqual(
            itinerary[0]["unavailable_candidates"],
            ["周一闭馆博物馆"],
        )

    def test_budget_uses_ranges_and_lists_unknown_costs(self):
        request = {
            "destination": "上海",
            "travelers": 3,
            "rooms": 2,
            "hotel_level": "comfortable",
            "currency": "CNY",
        }
        itinerary = [{"day": 1}, {"day": 2}, {"day": 3}]
        budget = calculate_budget(request, itinerary, [])
        self.assertLess(budget["total"][0], budget["total"][1])
        self.assertTrue(any("酒店实时价格" in item for item in budget["unknown_items"]))

    def test_ticket_budget_uses_actual_activities(self):
        request = {
            "destination": "上海",
            "travelers": 2,
            "rooms": 1,
            "hotel_level": "comfortable",
            "currency": "CNY",
            "budget_total": 5000,
        }
        itinerary = [
            {
                "activities": [
                    {
                        "name": "博物馆",
                        "ticket_price_min": 50,
                        "ticket_price_max": 80,
                        "currency": "CNY",
                    }
                ]
            },
            {"activities": []},
        ]
        budget = calculate_budget(request, itinerary, [])
        self.assertEqual(budget["items"]["景点门票"]["range"], (100, 160))
        self.assertEqual(budget["user_budget"], 5000)

    def test_no_activities_do_not_create_ticket_cost(self):
        request = {
            "travelers": 2,
            "hotel_level": "unspecified",
            "currency": "CNY",
        }
        budget = calculate_budget(request, [{"activities": []}], [])
        self.assertEqual(budget["items"]["景点门票"]["range"], (0, 0))

    def test_budget_status_reports_over_budget(self):
        request = {
            "destination": "上海",
            "travelers": 2,
            "rooms": 1,
            "hotel_level": "premium",
            "currency": "CNY",
            "budget_total": 1000,
        }
        hotels = [{
            "id": "hotel-1",
            "name": "测试酒店",
            "price_per_room_night_min": 900,
            "price_per_room_night_max": 1800,
            "currency": "CNY",
        }]
        budget = calculate_budget(
            request, [{"activities": []}, {"activities": []}], hotels
        )
        self.assertEqual(budget["completeness"], "complete")
        self.assertEqual(budget["risk"], "over_budget")

    def test_missing_hotel_price_makes_budget_incomplete(self):
        request = {
            "destination": "上海",
            "travelers": 2,
            "hotel_level": "comfortable",
            "currency": "CNY",
            "budget_total": 10000,
        }
        budget = calculate_budget(
            request, [{"activities": []}, {"activities": []}], []
        )
        self.assertEqual(budget["completeness"], "partial")
        self.assertEqual(budget["risk"], "unknown")
        self.assertIsNone(budget["remaining"])

    def test_unknown_destination_cost_profile_is_incomplete(self):
        request = {
            "destination": "巴黎",
            "travelers": 2,
            "currency": "CNY",
            "budget_total": 10000,
        }
        budget = calculate_budget(request, [{"activities": []}], [])
        self.assertEqual(budget["completeness"], "partial")
        self.assertEqual(budget["risk"], "unknown")
        self.assertIn("目的地餐饮消费", budget["critical_unknown_items"])

    def test_foreign_currency_does_not_relabel_cny_lodging_fallback(self):
        request = {
            "destination": "东京",
            "travelers": 2,
            "currency": "JPY",
            "hotel_level": "economy",
        }
        budget = calculate_budget(
            request, [{"activities": []}, {"activities": []}], []
        )
        self.assertIsNone(budget["items"]["住宿"]["range"])
        self.assertEqual(budget["items"]["住宿"]["confidence"], "unknown")
        self.assertEqual(budget["completeness"], "partial")

    def test_currency_alias_is_normalized(self):
        request = TripRequest(currency="人民币")
        self.assertEqual(request.currency, "CNY")

    def test_budget_optimizer_replaces_paid_activity(self):
        request = {
            "destination": "上海",
            "travelers": 2,
            "rooms": 1,
            "currency": "CNY",
            "budget_total": 1000,
        }
        hotels = [{
            "id": "hotel-1",
            "name": "测试酒店",
            "price_per_room_night_min": 200,
            "price_per_room_night_max": 300,
            "currency": "CNY",
        }]
        itinerary = [{
            "day": 1,
            "area": "黄浦区",
            "activities": [{
                "period": "上午",
                "attraction_id": "paid",
                "name": "收费景点",
                "ticket_price_min": 300,
                "ticket_price_max": 400,
                "currency": "CNY",
            }],
        }]
        attractions = [{
            "id": "free",
            "name": "免费景点",
            "area": "黄浦区",
            "ticket_price_min": 0,
            "ticket_price_max": 0,
            "currency": "CNY",
            "evidence": [],
        }]
        optimized, budget = optimize_plan_for_budget(
            request, itinerary, hotels, attractions
        )
        self.assertEqual(optimized[0]["activities"][0]["attraction_id"], "free")
        self.assertTrue(budget["adjustments"])

    def test_alternatives_use_unused_candidates_from_same_area(self):
        itinerary = [{
            "day": 1,
            "area": "黄浦区",
            "activities": [{"attraction_id": "used", "name": "已安排景点"}],
        }]
        alternatives = build_alternatives(itinerary, [
            {"id": "used", "name": "已安排景点", "area": "黄浦区"},
            {"id": "backup", "name": "同区备选", "area": "黄浦区"},
            {"id": "far", "name": "跨区景点", "area": "浦东新区"},
        ])
        self.assertEqual(alternatives[0]["candidate_names"], ["同区备选"])
        self.assertIn("同区备选", alternatives[0]["suggestion"])

    def test_partial_budget_can_still_optimize_known_overrun(self):
        request = {
            "destination": "上海",
            "travelers": 2,
            "rooms": 1,
            "currency": "CNY",
            "budget_total": 800,
            "hotel_level": "comfortable",
        }
        itinerary = [
            {
                "day": 1,
                "area": "黄浦区",
                "activities": [{
                    "period": "上午",
                    "attraction_id": "paid",
                    "name": "高价景点",
                    "ticket_price_min": 600,
                    "ticket_price_max": 700,
                    "currency": "CNY",
                }],
            },
            {"day": 2, "area": "黄浦区", "activities": []},
        ]
        attractions = [{
            "id": "free",
            "name": "免费景点",
            "area": "黄浦区",
            "ticket_price_min": 0,
            "ticket_price_max": 0,
            "currency": "CNY",
            "evidence": [],
        }]
        before = calculate_budget(request, itinerary, [])
        optimized, after = optimize_plan_for_budget(
            request, itinerary, [], attractions
        )
        self.assertEqual(before["completeness"], "partial")
        self.assertIn(before["risk"], {"at_risk", "over_budget"})
        self.assertEqual(
            optimized[0]["activities"][0]["attraction_id"], "free"
        )
        self.assertTrue(after["adjustments"])


if __name__ == "__main__":
    unittest.main()
