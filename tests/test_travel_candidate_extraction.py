import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from app.agents.travel.candidate_extraction import (
    _parse_price_range,
    extract_candidates,
    extract_with_page_enrichment,
)
from app.agents.travel.schemas import SearchDocument


def _model_result(payload: dict):
    return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))


class TravelCandidateExtractionTests(unittest.TestCase):
    def test_article_title_is_not_accepted_as_attraction(self):
        document = SearchDocument(
            id="doc-1",
            purpose="attractions",
            title="上海必去十大景点完整攻略",
            url="https://example.com/guide",
            snippet="上海必去十大景点完整攻略",
        )
        payload = {"candidates": [{
            "name": "上海必去十大景点完整攻略",
            "candidate_type": "attraction",
            "subtype": "other_attraction",
            "evidence": [{
                "document_id": "doc-1",
                "source_url": document.url,
                "name_quote": document.snippet,
                "type_quote": document.snippet,
            }],
        }]}
        with patch("app.agents.travel.candidate_extraction.get_llm") as llm:
            llm.return_value.invoke.return_value = _model_result(payload)
            result = extract_candidates(
                [document], destination="上海", purpose="attractions"
            )
        self.assertEqual(result, [])

    def test_verified_fields_are_parsed_from_verbatim_quotes(self):
        document = SearchDocument(
            id="doc-1",
            purpose="attractions",
            title="上海市文化旅游介绍",
            url="https://example.com/shanghai",
            snippet=(
                "上海博物馆是一座综合性博物馆，位于黄浦区。"
                "上海博物馆成人票50元，旺季票价80元。"
            ),
        )
        payload = {"candidates": [{
            "name": "上海博物馆",
            "candidate_type": "attraction",
            "subtype": "museum",
            "area": "黄浦区",
            "evidence": [{
                "document_id": "doc-1",
                "source_url": document.url,
                "name_quote": "上海博物馆是一座综合性博物馆",
                "type_quote": "上海博物馆是一座综合性博物馆",
                "area_quote": "位于黄浦区",
                "ticket_price_quote": "上海博物馆成人票50元，旺季票价80元",
            }],
        }]}
        with patch("app.agents.travel.candidate_extraction.get_llm") as llm:
            llm.return_value.invoke.return_value = _model_result(payload)
            result = extract_candidates(
                [document], destination="上海", purpose="attractions"
            )
        self.assertEqual(result[0]["name"], "上海博物馆")
        self.assertEqual(result[0]["area"], "黄浦区")
        self.assertEqual(result[0]["ticket_price_min"], 50)
        self.assertEqual(result[0]["ticket_price_max"], 80)
        self.assertEqual(result[0]["evidence"][0]["source_title"], document.title)

    def test_hallucinated_price_quote_is_not_accepted(self):
        document = SearchDocument(
            id="doc-1",
            purpose="hotels",
            title="上海住宿介绍",
            url="https://example.com/hotel",
            snippet="上海和平酒店提供酒店住宿，位于上海市中心。",
        )
        payload = {"candidates": [{
            "name": "上海和平酒店",
            "candidate_type": "hotel",
            "subtype": "hotel",
            "evidence": [{
                "document_id": "doc-1",
                "source_url": document.url,
                "name_quote": "上海和平酒店提供酒店住宿",
                "type_quote": "提供酒店住宿",
                "hotel_price_quote": "每间每晚500至900元",
            }],
        }]}
        with patch("app.agents.travel.candidate_extraction.get_llm") as llm:
            llm.return_value.invoke.return_value = _model_result(payload)
            result = extract_candidates(
                [document], destination="上海", purpose="hotels"
            )
        self.assertIsNone(result[0]["price_per_room_night_min"])
        self.assertIsNone(result[0]["price_per_room_night_max"])

    def test_restaurant_cannot_be_labeled_as_attraction(self):
        document = SearchDocument(
            id="doc-1",
            purpose="attractions",
            title="上海餐饮",
            url="https://example.com/food",
            snippet="上海老饭店是上海泰山主题餐厅。",
        )
        payload = {"candidates": [{
            "name": "上海老饭店",
            "candidate_type": "attraction",
            "subtype": "natural_site",
            "evidence": [{
                "document_id": "doc-1",
                "source_url": document.url,
                "name_quote": "上海老饭店是上海泰山主题餐厅",
                "type_quote": "上海泰山主题餐厅",
            }],
        }]}
        with patch("app.agents.travel.candidate_extraction.get_llm") as llm:
            llm.return_value.invoke.return_value = _model_result(payload)
            result = extract_candidates(
                [document], destination="上海", purpose="attractions"
            )
        self.assertEqual(result, [])

    def test_page_enrichment_is_bounded_and_keeps_existing_candidates(self):
        documents = [
            SearchDocument(
                id=f"doc-{i}",
                purpose="attractions",
                title=f"上海资料{i}",
                url=f"https://example.com/{i}",
                snippet="上海景点资料",
            )
            for i in range(3)
        ]
        existing = {
            "id": "attraction-1",
            "name": "上海博物馆",
            "candidate_type": "attraction",
            "subtype": "museum",
            "destination": "上海",
            "evidence": [],
            "confidence": "medium",
        }
        with (
            patch(
                "app.agents.travel.candidate_extraction.extract_candidates",
                side_effect=[[existing], []],
            ),
            patch(
                "app.agents.travel.candidate_extraction.fetch_webpage_text",
                return_value={"url": "https://example.com", "text": "正文"},
            ) as fetch,
        ):
            result, issues = extract_with_page_enrichment(
                documents,
                destination="上海",
                purpose="attractions",
                minimum=3,
                max_pages=2,
            )
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(result[0]["name"], "上海博物馆")
        self.assertEqual(issues, [])

    def test_search_document_rejects_non_http_url(self):
        with self.assertRaises(ValidationError):
            SearchDocument(
                id="bad",
                purpose="attractions",
                title="bad",
                url="javascript:alert(1)",
            )

    def test_candidate_destination_must_share_local_context(self):
        document = SearchDocument(
            id="doc-1",
            purpose="hotels",
            title="上海与北京住宿推荐",
            url="https://example.com/multi-city-hotels",
            snippet="上海住宿很多。北京饭店是一家五星级酒店，每晚人民币800元。",
        )
        payload = {"candidates": [{
            "name": "北京饭店",
            "candidate_type": "hotel",
            "subtype": "hotel",
            "evidence": [{
                "document_id": "doc-1",
                "source_url": document.url,
                "name_quote": "北京饭店",
                "type_quote": "北京饭店是一家五星级酒店",
                "hotel_price_quote": "每晚人民币800元",
            }],
        }]}
        with patch("app.agents.travel.candidate_extraction.get_llm") as llm:
            llm.return_value.invoke.return_value = _model_result(payload)
            result = extract_candidates(
                [document], destination="上海", purpose="hotels"
            )
        self.assertEqual(result, [])

    def test_verified_context_quote_can_link_destination(self):
        document = SearchDocument(
            id="doc-1",
            purpose="hotels",
            title="住宿资料",
            url="https://example.com/shanghai-hotel",
            snippet="和平饭店是位于上海外滩的酒店，每晚¥800。",
        )
        payload = {"candidates": [{
            "name": "和平饭店",
            "candidate_type": "hotel",
            "subtype": "hotel",
            "evidence": [{
                "document_id": "doc-1",
                "source_url": document.url,
                "name_quote": "和平饭店",
                "type_quote": "和平饭店是位于上海外滩的酒店",
                "context_quote": "和平饭店是位于上海外滩的酒店",
                "hotel_price_quote": "每晚¥800",
            }],
        }]}
        with patch("app.agents.travel.candidate_extraction.get_llm") as llm:
            llm.return_value.invoke.return_value = _model_result(payload)
            result = extract_candidates(
                [document], destination="上海", purpose="hotels"
            )
        self.assertEqual(result[0]["name"], "和平饭店")

    def test_symbol_price_range_parses_both_bounds(self):
        self.assertEqual(
            _parse_price_range("房价 ¥300-500/晚", hotel=True),
            (300, 500, "CNY"),
        )
        self.assertEqual(
            _parse_price_range("USD $80–$120 per night", hotel=True),
            (80, 120, "USD"),
        )

    def test_type_quote_must_be_bound_to_candidate(self):
        document = SearchDocument(
            id="doc-1",
            purpose="hotels",
            title="上海本地生活",
            url="https://example.com/local",
            snippet="上海老王米粉店很好吃。附近酒店很多。",
        )
        payload = {"candidates": [{
            "name": "老王米粉店",
            "candidate_type": "hotel",
            "subtype": "hotel",
            "evidence": [{
                "document_id": "doc-1",
                "source_url": document.url,
                "name_quote": "上海老王米粉店很好吃",
                "type_quote": "附近酒店很多",
                "context_quote": "上海老王米粉店很好吃",
            }],
        }]}
        with patch("app.agents.travel.candidate_extraction.get_llm") as llm:
            llm.return_value.invoke.return_value = _model_result(payload)
            result = extract_candidates(
                [document], destination="上海", purpose="hotels"
            )
        self.assertEqual(result, [])

    def test_optional_quote_from_another_candidate_is_discarded(self):
        document = SearchDocument(
            id="doc-1",
            purpose="hotels",
            title="上海酒店",
            url="https://example.com/hotels",
            snippet="上海甲酒店提供住宿。乙酒店每晚¥900。",
        )
        payload = {"candidates": [{
            "name": "甲酒店",
            "candidate_type": "hotel",
            "subtype": "hotel",
            "evidence": [{
                "document_id": "doc-1",
                "source_url": document.url,
                "name_quote": "上海甲酒店提供住宿",
                "type_quote": "上海甲酒店提供住宿",
                "context_quote": "上海甲酒店提供住宿",
                "hotel_price_quote": "乙酒店每晚¥900",
            }],
        }]}
        with patch("app.agents.travel.candidate_extraction.get_llm") as llm:
            llm.return_value.invoke.return_value = _model_result(payload)
            result = extract_candidates(
                [document], destination="上海", purpose="hotels"
            )
        self.assertIsNone(result[0]["price_per_room_night_min"])

    def test_directional_single_price_is_not_an_exact_range(self):
        self.assertIsNone(_parse_price_range("每晚 ¥500起", hotel=True))
        self.assertIsNone(_parse_price_range("票价不超过100元", hotel=False))


if __name__ == "__main__":
    unittest.main()
