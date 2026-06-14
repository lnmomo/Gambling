import unittest

from football_agents.llm.ops_agent import QwenOpsAgent


class _Client:
    def __init__(self):
        self.user = ""

    def chat_json(self, system, user, **kwargs):
        self.user = user
        return {"summary": "数据完整", "status": "healthy", "data_quality_score": 0.95,
                "risks": [], "actions": []}


class QwenOpsTests(unittest.TestCase):
    def test_review_is_structured_and_does_not_replace_original_output(self):
        output = {"records": 40, "status": "success"}
        reviewed = QwenOpsAgent(_Client()).attach("official-data-agent", output)
        self.assertEqual(40, reviewed["records"])
        self.assertEqual("healthy", reviewed["qwen_review"]["status"])

    def test_review_keeps_verified_numeric_facts(self):
        client = _Client()
        reviewed = QwenOpsAgent(client).attach("market-news-weather-agent", {
            "matches": 10, "market_odds": 2, "news": 0, "news_existing": 41,
            "weather_missing_metadata": 10, "news_status": "up_to_date",
            "model_status": "baseline_only", "errors": [],
        })
        facts = reviewed["qwen_review"]["verified_facts"]
        self.assertEqual(2, facts["market_odds"])
        self.assertEqual(41, facts["news_existing"])
        self.assertEqual("up_to_date", facts["news_status"])
        self.assertIn("唯一事实来源", client.user)


if __name__ == "__main__":
    unittest.main()
