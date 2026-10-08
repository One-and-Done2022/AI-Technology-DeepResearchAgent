from __future__ import annotations

import json

from src.planner.planner import Planner


def test_planner_caps_external_benchmark_tasks_and_keeps_verification() -> None:
    planner = Planner(policy=lambda messages: {"content": ""})
    plan = {
        "sub_tasks": [
            {"task_id": "task_1", "task_type": "search", "description": "search"},
            {"task_id": "task_2", "task_type": "search", "description": "search 2"},
            {"task_id": "task_3", "task_type": "analyze", "description": "analyze"},
            {"task_id": "task_4", "task_type": "verify", "description": "verify", "verification_required": True},
            {"task_id": "task_5", "task_type": "search", "description": "extra"},
        ]
    }
    dag = planner._parse_plan(json.dumps(plan), max_tasks=4)
    assert len(dag) == 4
    assert dag.has_node("task_4")
