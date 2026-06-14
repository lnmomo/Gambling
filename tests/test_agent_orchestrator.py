import tempfile
import unittest
from pathlib import Path

from football_agents.agents.orchestrator import AgentOrchestrator
from football_agents.agents.workflow import DecisionWorkflow
from football_agents.db import Database
from football_agents.repository import Repository


class _QwenStub:
    def configured(self):
        return True

    def status(self):
        return {"configured": True, "provider": "qwen", "model": "qwen-flash", "base_host": "example"}


class _QwenOpsStub:
    def attach(self, agent_name, output):
        return {**output, "qwen_review": {"summary": f"reviewed {agent_name}", "status": "healthy",
                "data_quality_score": 1.0, "risks": [], "actions": []}}


class AgentOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        database = Database(Path(self.temp.name) / "agents.db")
        database.initialize()
        self.repository = Repository(database)

    def tearDown(self):
        self.temp.cleanup()

    def test_run_persists_real_step_statuses(self):
        orchestrator = AgentOrchestrator(self.repository)
        orchestrator.official.sync = lambda force=False: {"status": "success", "records": 0}
        orchestrator.enrichment.sync = lambda limit, evaluate=False: {"matches": 0, "errors": []}
        orchestrator.qwen = _QwenStub()
        orchestrator.qwen_ops = _QwenOpsStub()
        result = orchestrator.run(limit=5)
        self.assertEqual("success", result["status"])
        self.assertEqual(4, len(result["steps"]))
        self.assertTrue(all(step["status"] == "success" for step in result["steps"]))
        self.assertTrue(all("qwen_review" in step["output"] for step in result["steps"]))

    def test_qwen_context_requires_evidence_and_normalizes(self):
        base = {"home": 0.4, "draw": 0.3, "away": 0.3}
        analysis = {"id": 1, "provider": "qwen", "model": "qwen-flash", "analysis": {
            "news_confidence": 0.8, "home_team_impact": 0.05, "away_team_impact": -0.02,
            "evidence": ["source"],
        }}
        adjusted, metadata = DecisionWorkflow._apply_llm_context(base, analysis)
        self.assertTrue(metadata["applied"])
        self.assertAlmostEqual(1.0, sum(adjusted.values()))
        self.assertGreater(adjusted["home"], base["home"])

        unchanged, metadata = DecisionWorkflow._apply_llm_context(base, {**analysis, "analysis": {
            **analysis["analysis"], "evidence": [],
        }})
        self.assertFalse(metadata["applied"])
        self.assertEqual(base, unchanged)


if __name__ == "__main__":
    unittest.main()
