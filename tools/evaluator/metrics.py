"""Shared statistics and result-file helpers for the evaluator.

The browser never imports this module and no API response includes a machine
label. Machine answers are joined to human labels here, for scoring only.
Everything uses the Python standard library.
"""

from __future__ import annotations

import csv
import math
import os
from collections import Counter


Z_95 = 1.96
RATERS = ("primary",)
RATER_LABELS = {"primary": "Rater 1"}
REJECT_REASONS = (
    "The maker is clearly a professional developer",
    "This is a tutorial, course exercise, or template",
    "The link is broken so I cannot tell",
    "The page is a placeholder with no real content",
    "It is not software at all",
    "Other",
)
FIELDNAMES = (
    "item_id",
    "rater_id",
    "assigned",
    "verdict",
    "human_label",
    "corrected_label",
    "belongs",
    "reject_reason",
    "reject_other",
    "note",
    "judged_utc",
)
FINAL_ACTIONS = ("label", "reject")
ALL_ACTIONS = FINAL_ACTIONS + ("skip", "undo")


def sample_size(p, margin, population, z=Z_95):
    """Return formula-based n with the finite population correction."""
    if population <= 0 or not 0 < p < 1 or margin <= 0:
        return 0
    n0 = z * z * p * (1 - p) / (margin * margin)
    return math.ceil(n0 / (1 + (n0 - 1) / population))


def design_margin(n, p, population, z=Z_95):
    """Margin implied by n and an assumed p, including finite correction."""
    if n <= 1 or population <= 1 or not 0 < p < 1:
        return None
    used = min(n, population)
    fpc = math.sqrt((population - used) / (population - 1))
    return z * math.sqrt(p * (1 - p) / used) * fpc


def wilson_interval(successes, total, z=Z_95):
    """Wilson score interval for a binomial proportion."""
    if total <= 0:
        return None
    p = successes / total
    den = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / den
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def cohen_kappa(pairs):
    """Cohen's kappa for pairs of categorical labels."""
    if not pairs:
        return None
    total = len(pairs)
    left = Counter(a for a, _ in pairs)
    right = Counter(b for _, b in pairs)
    observed = sum(1 for a, b in pairs if a == b) / total
    expected = sum(left[key] * right[key] for key in set(left) | set(right)) / (total * total)
    if math.isclose(expected, 1.0):
        return 1.0 if math.isclose(observed, 1.0) else None
    return (observed - expected) / (1 - expected)


def _clean(value):
    return " ".join(str(value or "").split())


def normalise_row(row):
    """Read both the original agree/disagree schema and the direct-label schema."""
    verdict = _clean(row.get("verdict")).lower()
    assigned = _clean(row.get("assigned"))
    human = _clean(row.get("human_label"))
    corrected = _clean(row.get("corrected_label"))
    belongs = _clean(row.get("belongs")).lower()
    rater = _clean(row.get("rater_id")) or "primary"
    if rater not in RATERS:
        rater = "primary"

    if verdict == "agree":
        verdict, human, belongs = "label", assigned, "yes"
    elif verdict == "disagree":
        verdict, human, belongs = "label", corrected, "yes"
    elif verdict == "unsure":
        verdict, human, belongs = "label", "Cannot tell", "yes"
    elif verdict not in ALL_ACTIONS:
        verdict = ""

    if verdict == "label" and not belongs:
        belongs = "yes"
    if verdict == "reject":
        belongs = "no"
        human = ""

    return {
        "item_id": _clean(row.get("item_id")),
        "rater_id": rater,
        "assigned": assigned,
        "verdict": verdict,
        "human_label": human,
        "corrected_label": corrected,
        "belongs": belongs,
        "reject_reason": _clean(row.get("reject_reason")),
        "reject_other": _clean(row.get("reject_other")),
        "note": _clean(row.get("note")),
        "judged_utc": _clean(row.get("judged_utc")),
    }


def read_rows(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", newline="") as handle:
            return [normalise_row(row) for row in csv.DictReader(handle) if row.get("item_id")]
    except (OSError, csv.Error):
        return []


def latest_rows(rows, rater_id):
    """Last append-only action per item for one rater."""
    latest = {}
    for row in rows:
        if row["rater_id"] == rater_id and row["item_id"]:
            latest[row["item_id"]] = row
    return latest


def migrate_file(path):
    """Upgrade an old result header atomically while preserving every row."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return
    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        header = tuple(reader.fieldnames or ())
        if header == FIELDNAMES:
            return
        rows = [normalise_row(row) for row in reader if row.get("item_id")]
    temp = path + ".migrating"
    with open(temp, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def append_row(path, row):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    migrate_file(path)
    new_file = not os.path.exists(path) or os.path.getsize(path) == 0
    clean = normalise_row(row)
    with open(path, "a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        if new_file:
            writer.writeheader()
        writer.writerow(clean)
        handle.flush()
        os.fsync(handle.fileno())


def _population_specs(task):
    specs = (task.get("sampling") or {}).get("populations") or []
    if specs:
        return specs
    return [{
        "id": "all",
        "label": "All sampled items",
        "N": len(task.get("items") or []),
        "assumed_p": 0.5,
        "target_margin": None,
        "target_n": len(task.get("items") or []),
    }]


def task_progress(task, rows, rater_id):
    """Blind-safe progress statistics. No agreement value is returned."""
    latest = latest_rows(rows, rater_id)
    item_ids = {item["id"] for item in task.get("items") or []}
    judged = sum(
        1 for item_id, row in latest.items()
        if item_id in item_ids and row["verdict"] in FINAL_ACTIONS
    )
    skipped = sum(
        1 for item_id, row in latest.items()
        if item_id in item_ids and row["verdict"] == "skip"
    )
    rejected = sum(
        1 for item_id, row in latest.items()
        if item_id in item_ids and row["verdict"] == "reject"
    )

    margins = []
    for spec in _population_specs(task):
        pop_id = spec.get("id", "all")
        ids = {
            item["id"] for item in task.get("items") or []
            if (item.get("population") or "all") == pop_id
        }
        n = sum(
            1 for item_id, row in latest.items()
            if item_id in ids and row["verdict"] in FINAL_ACTIONS
        )
        margin = design_margin(n, float(spec.get("assumed_p", 0.5)), int(spec.get("N", len(ids))))
        if margin is not None:
            margins.append(margin)

    return {
        "n_items": len(item_ids),
        "n_judged": judged,
        "n_skipped": skipped,
        "n_rejected": rejected,
        "widest_margin": max(margins) if len(margins) == len(_population_specs(task)) else None,
    }


def _score_group(task, latest, spec):
    pop_id = spec.get("id", "all")
    items = [
        item for item in task.get("items") or []
        if (item.get("population") or "all") == pop_id
    ]
    machine = {item["id"]: item.get("assigned", "") for item in items}
    current = {item_id: latest[item_id] for item_id in machine if item_id in latest}
    judged = [row for row in current.values() if row["verdict"] in FINAL_ACTIONS]
    rejected = [row for row in judged if row["verdict"] == "reject"]
    labelled = [row for row in judged if row["verdict"] == "label"]
    cannot_label = _clean(task.get("cannot_tell")).casefold()
    usable = [
        row for row in labelled
        if not cannot_label or row["human_label"].casefold() != cannot_label
    ]
    cannot = len(labelled) - len(usable)
    pairs = [(machine[row["item_id"]], row["human_label"]) for row in usable
             if _clean(machine[row["item_id"]])]
    missing_machine = len(usable) - len(pairs)
    agreements = sum(1 for assigned, human in pairs if assigned == human)
    confusion = Counter((assigned or "(no label)", human or "(blank)")
                        for assigned, human in pairs if assigned != human)
    reason_counts = Counter(row["reject_reason"] or "(reason missing)" for row in rejected)
    skipped = sum(1 for row in current.values() if row["verdict"] == "skip")
    do_kappa = bool((task.get("scoring") or {}).get("cohen_kappa"))
    return {
        "population_id": pop_id,
        "population_label": spec.get("label") or pop_id,
        "population_N": int(spec.get("N", len(items))),
        "sample_n": len(items),
        "n_judged": len(judged),
        "n_labelled": len(labelled),
        "n_skipped": skipped,
        "n_rejected": len(rejected),
        "n_cannot_tell": cannot,
        "n_usable": len(pairs),
        "n_missing_machine": missing_machine,
        "n_agree": agreements,
        "agreement": agreements / len(pairs) if pairs else None,
        "agreement_ci": wilson_interval(agreements, len(pairs)),
        "kappa": cohen_kappa(pairs) if do_kappa else None,
        "rejection_rate": len(rejected) / len(judged) if judged else None,
        "rejection_ci": wilson_interval(len(rejected), len(judged)),
        "reasons": reason_counts,
        "confusion": confusion,
        "target_margin": spec.get("target_margin"),
        "target_n": spec.get("target_n"),
        "assumed_p": spec.get("assumed_p"),
    }


def analyse_task(task, rows, rater_id):
    latest = latest_rows(rows, rater_id)
    groups = [_score_group(task, latest, spec) for spec in _population_specs(task)]
    task_ids = {item["id"] for item in task.get("items") or []}
    orphans = sum(1 for item_id in latest if item_id not in task_ids)
    return {"task_id": task["task_id"], "rater_id": rater_id, "groups": groups, "orphans": orphans}



def _percent(value, digits=1):
    return "not available" if value is None else ("%.*f%%" % (digits, value * 100))


def methods_text(tasks, labels_dir, rater_id="primary"):
    """Build paste-ready methods and results prose from current files."""
    design_parts = []
    result_parts = []
    for task in tasks:
        sampling = task.get("sampling") or {}
        specs = _population_specs(task)
        sample_bits = []
        for spec in specs:
            margin = spec.get("target_margin")
            sample_bits.append(
                "%s (N=%s, n=%s, assumed p=%s, target margin=%s)"
                % (
                    spec.get("label") or spec.get("id"),
                    format(int(spec.get("N", 0)), ","),
                    spec.get("target_n", len(task.get("items") or [])),
                    spec.get("assumed_p", "not stated"),
                    ("%.0f percentage points" % (100 * float(margin))) if margin else "not stated",
                )
            )
        design_parts.append(
            "%s used %s with seed %s: %s."
            % (
                task.get("title", task["task_id"]),
                sampling.get("method", "a reproducible random sample"),
                sampling.get("seed", "not stated"),
                "; ".join(sample_bits),
            )
        )

        rows = read_rows(os.path.join(labels_dir, task["task_id"] + ".csv"))
        analysis = analyse_task(task, rows, rater_id)
        for group in analysis["groups"]:
            if not group["n_judged"]:
                continue
            agreement_ci = group["agreement_ci"]
            reject_ci = group["rejection_ci"]
            kappa = "not calculated" if group["kappa"] is None else "%.2f" % group["kappa"]
            judged_noun = "item" if group["n_judged"] == 1 else "items"
            rejected_clause = (
                "1 item was rejected"
                if group["n_rejected"] == 1
                else "%d items were rejected" % group["n_rejected"]
            )
            cannot_tell_clause = (
                "1 cannot-tell response was excluded"
                if group["n_cannot_tell"] == 1
                else "%d cannot-tell responses were excluded" % group["n_cannot_tell"]
            )
            if group["n_missing_machine"]:
                cannot_tell_clause += "; %d otherwise usable responses had no machine label to compare" % group["n_missing_machine"]
            result_parts.append(
                "For %s (%s), %s judged %d %s. Agreement was %s%s (Cohen's kappa %s), "
                "%s; %s, a rate of %s%s."
                % (
                    group["population_label"],
                    task["task_id"],
                    RATER_LABELS[rater_id],
                    group["n_judged"],
                    judged_noun,
                    _percent(group["agreement"]),
                    (
                        " (95%% Wilson CI %.1f%% to %.1f%%)"
                        % (agreement_ci[0] * 100, agreement_ci[1] * 100)
                    ) if agreement_ci else "",
                    kappa,
                    cannot_tell_clause,
                    rejected_clause,
                    _percent(group["rejection_rate"]),
                    (
                        " (95%% Wilson CI %.1f%% to %.1f%%)"
                        % (reject_ci[0] * 100, reject_ci[1] * 100)
                    ) if reject_ci else "",
                )
            )

    intro = (
        "Sample sizes were calculated as n = z²p(1-p)/e² at 95% confidence and adjusted "
        "with the finite population correction. Rows were randomly ordered so that an early "
        "stopping point retained a random prefix. "
    )
    methods = intro + " ".join(design_parts)
    results = " ".join(result_parts) if result_parts else "No completed judgements were available for results."
    return "Methods\n\n%s\n\nResults\n\n%s\n" % (methods, results)


def write_methods(tasks, labels_dir, rater_id="primary"):
    os.makedirs(labels_dir, exist_ok=True)
    path = os.path.join(labels_dir, "methods.txt")
    temp = path + ".writing"
    with open(temp, "w", encoding="utf-8") as handle:
        handle.write(methods_text(tasks, labels_dir, rater_id))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    return path
