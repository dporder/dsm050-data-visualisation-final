"""Standard-library regression tests for the research instrument."""

from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest

import metrics
import serve


class StatisticsTests(unittest.TestCase):
    def test_formula_sample_sizes_match_protocol(self):
        self.assertEqual(metrics.sample_size(0.8, 0.10, 16818), 62)
        self.assertEqual(metrics.sample_size(0.5, 0.15, 24213), 43)
        self.assertEqual(metrics.sample_size(0.8, 0.11, 5834), 51)

    def test_wilson_interval_contains_observed_proportion(self):
        low, high = metrics.wilson_interval(18, 20)
        self.assertLess(low, 0.9)
        self.assertGreater(high, 0.9)

    def test_kappa_perfect_and_chance(self):
        self.assertEqual(metrics.cohen_kappa([("a", "a"), ("b", "b")]), 1.0)
        self.assertAlmostEqual(
            metrics.cohen_kappa([("a", "a"), ("a", "b"), ("b", "a"), ("b", "b")]),
            0.0,
        )

    def test_unknown_rater_id_normalises_to_the_only_rater(self):
        row = metrics.normalise_row({"item_id": "one", "rater_id": "second", "verdict": "label", "human_label": "A"})
        self.assertEqual(row["rater_id"], "primary")
        self.assertEqual(metrics.RATERS, ("primary",))

    def test_missing_machine_labels_are_not_disagreements(self):
        task = {"task_id": "check", "cannot_tell": "Cannot tell", "scoring": {"cohen_kappa": True},
                "items": [{"id": "one", "assigned": "A"}, {"id": "two", "assigned": " "},
                          {"id": "three", "assigned": "B"}, {"id": "four", "assigned": "A"}]}
        rows = [metrics.normalise_row({"item_id": i, "verdict": "label", "human_label": label})
                for i, label in [("one", "A"), ("two", "B"), ("three", "A"), ("four", "Cannot tell")]]
        group = metrics.analyse_task(task, rows, "primary")["groups"][0]
        self.assertEqual(group["n_usable"], 2)
        self.assertEqual(group["n_missing_machine"], 1)
        self.assertEqual(group["n_cannot_tell"], 1)
        self.assertEqual(group["agreement"], 0.5)
        self.assertEqual(dict(group["confusion"]), {("B", "A"): 1})

    def test_export_without_machine_labels_has_no_false_zero_agreement(self):
        task = {"task_id": "check", "items": [{"id": "one", "assigned": ""}]}
        with tempfile.TemporaryDirectory() as directory:
            metrics.append_row(os.path.join(directory, "check.csv"),
                               {"item_id": "one", "verdict": "label", "human_label": "A"})
            prose = metrics.methods_text([task], directory)
        self.assertIn("Agreement was not available", prose)
        self.assertIn("no machine label to compare", prose)
        self.assertNotIn("Agreement was 0.0%", prose)

class StorageTests(unittest.TestCase):
    def test_old_csv_migrates_without_losing_judgement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "task.csv")
            with open(path, "w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "item_id", "assigned", "verdict", "corrected_label", "note", "judged_utc"
                ])
                writer.writeheader()
                writer.writerow({
                    "item_id": "one", "assigned": "Machine A", "verdict": "disagree",
                    "corrected_label": "Human B", "note": "kept", "judged_utc": "now",
                })
            metrics.append_row(path, {
                "item_id": "two", "rater_id": "second", "assigned": "Machine B",
                "verdict": "reject", "belongs": "no",
                "reject_reason": metrics.REJECT_REASONS[0], "judged_utc": "later",
            })
            rows = metrics.read_rows(path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["human_label"], "Human B")
            self.assertEqual(rows[0]["rater_id"], "primary")
            self.assertEqual(rows[1]["verdict"], "reject")
            with open(path, "r", encoding="utf-8", newline="") as handle:
                self.assertEqual(tuple(csv.reader(handle).__next__()), metrics.FIELDNAMES)


class BlindApiTests(unittest.TestCase):
    def test_public_payload_has_no_machine_keys(self):
        tasks, problems = serve.discover_tasks()
        self.assertFalse(problems)
        self.assertTrue(tasks)
        payload = serve.public_task(tasks[0], "primary")

        def keys(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield key
                    yield from keys(child)
            elif isinstance(value, list):
                for child in value:
                    yield from keys(child)

        all_keys = set(keys(payload))
        self.assertNotIn("assigned", all_keys)
        self.assertNotIn("population", all_keys)

    def test_generated_tasks_match_formula_targets(self):
        tasks = {task["task_id"]: task for task in serve.discover_tasks()[0]}
        self.assertEqual(set(tasks), {"kind", "audience", "maker", "namestyle"})
        for task in tasks.values():
            self.assertEqual(len(task["items"]), 50)
            self.assertEqual(sum(p["target_n"] for p in task["sampling"]["populations"]), 50)


if __name__ == "__main__":
    unittest.main()
