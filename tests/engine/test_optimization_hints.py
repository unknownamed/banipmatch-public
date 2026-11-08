"""A complete hint must describe a feasible full model, including auxiliaries."""
from copy import deepcopy
import json
from pathlib import Path
from time import monotonic
import unittest

from ortools.sat.python import cp_model

from backend.engine import solve
from backend.engine.context import Context
from backend.engine.optimization import DispatchModel

ROOT = Path(__file__).resolve().parents[2]


def load(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


class CompleteHintTests(unittest.TestCase):
    def check_hint(self, snapshot):
        config = dict(seed=0, time_limit_seconds=10)
        incumbent = solve(snapshot, "B1", config)
        model = DispatchModel(Context(snapshot, config), monotonic() + 10)
        before_constraints = [str(constraint) for constraint in model.model.proto.constraints]
        model.hint(incumbent["assignments"])
        proto = model.model.proto
        self.assertEqual(set(proto.solution_hint.vars), set(range(len(proto.variables))))
        self.assertEqual(len(proto.solution_hint.vars), len(proto.variables))
        self.assertEqual([str(constraint) for constraint in proto.constraints], before_constraints)
        # Fixing hints is test-only: every helper must agree with route/time
        # constraints, not merely have a value of the right type.
        verifier = cp_model.CpSolver()
        verifier.parameters.fix_variables_to_their_hinted_value = True
        verifier.parameters.num_search_workers = 1
        verifier.parameters.max_time_in_seconds = 5
        self.assertIn(verifier.solve(model.model), (cp_model.OPTIMAL, cp_model.FEASIBLE))
        self.assertEqual(model.extract(verifier)[1], incumbent["unassigned_job_ids"])
        self.assertEqual(sorted(model.extract(verifier)[0], key=lambda x: x["job_id"]),
                         sorted(incumbent["assignments"], key=lambda x: x["job_id"]))
        model.hint(incumbent["assignments"])
        self.assertEqual(len(proto.solution_hint.vars), len(proto.variables))

    def test_departed_prefix_and_unassigned_work(self):
        self.check_hint(load("docs/development/v0.1/예제 데이터/01_snapshot.json"))

    def test_future_fixed_reservation_and_mixed_equipment(self):
        self.check_hint(load("docs/experiments/engine-sensitivity-2026-11-08/inputs/mixed_fixed_12.json"))

    def test_empty_routes_and_unselected_comparison_flags(self):
        snapshot = load("docs/development/v0.1/예제 데이터/01_snapshot.json")
        for job in snapshot["jobs"]:
            if not job["frozen"]:
                job["ready_at"] = "2026-11-07T23:00:00Z"
        self.check_hint(snapshot)

    def test_reversed_original_order_and_vehicle_change_flags(self):
        snapshot = load("docs/experiments/engine-sensitivity-2026-11-08/inputs/mixed_12.json")
        snapshot["baseline_assignments"] = deepcopy(snapshot["baseline_assignments"])
        for row in snapshot["baseline_assignments"]:
            row["sequence"] = len(snapshot["jobs"]) + 1 - row["sequence"]
        self.check_hint(snapshot)


if __name__ == "__main__":
    unittest.main()
