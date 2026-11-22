import unittest

from integrations.ai_platform.contracts import TaskEnvelope, TaskResult


class TaskEnvelopeTests(unittest.TestCase):
    def test_create_and_round_trip(self):
        task = TaskEnvelope.create(
            project="crypto-research",
            agent="market-analysis",
            action="analyze_market",
            input={"symbols": ["BTCUSDT"]},
            constraints={"read_only": True},
        )
        restored = TaskEnvelope.from_dict(task.to_dict())
        self.assertEqual(restored.task_id, task.task_id)
        self.assertEqual(restored.project, "crypto-research")
        self.assertEqual(restored.input, {"symbols": ["BTCUSDT"]})

    def test_invalid_priority_fails_closed(self):
        task = TaskEnvelope.create(
            project="crypto-research",
            agent="market-analysis",
            action="analyze_market",
        )
        invalid = task.to_dict()
        invalid["priority"] = "execute-live"
        with self.assertRaisesRegex(ValueError, "priority"):
            TaskEnvelope.from_dict(invalid)

    def test_unsupported_schema_version_is_rejected(self):
        task = TaskEnvelope.create(
            project="crypto-research",
            agent="market-analysis",
            action="analyze_market",
        ).to_dict()
        task["schema_version"] = "99.0"
        with self.assertRaisesRegex(ValueError, "schema version"):
            TaskEnvelope.from_dict(task)

    def test_approval_flag_must_be_boolean(self):
        task = TaskEnvelope.create(
            project="crypto-research",
            agent="execution",
            action="paper_order",
        ).to_dict()
        task["approval_required"] = "false"
        with self.assertRaisesRegex(ValueError, "boolean"):
            TaskEnvelope.from_dict(task)


class TaskResultTests(unittest.TestCase):
    def test_result_round_trip(self):
        result = TaskResult(
            task_id="task-123",
            status="completed",
            result={"eligible": False},
            evidence=[{"source": "unit-test"}],
            metrics={"checks": 3},
        )
        restored = TaskResult.from_dict(result.to_dict())
        self.assertEqual(restored.status, "completed")
        self.assertEqual(restored.evidence[0]["source"], "unit-test")

    def test_confidence_out_of_range_is_rejected(self):
        result = TaskResult(
            task_id="task-123",
            status="completed",
            confidence=1.5,
        )
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            result.validate()

    def test_invalid_status_is_rejected(self):
        result = TaskResult(task_id="task-123", status="live_order_sent")
        with self.assertRaisesRegex(ValueError, "status"):
            result.validate()


if __name__ == "__main__":
    unittest.main()
