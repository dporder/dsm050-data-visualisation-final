#!/usr/bin/env python3
"""Score direct human judgments without exposing machine labels to the browser.

Usage:
    python3 tools/evaluator/score.py
    python3 tools/evaluator/score.py genre
    python3 tools/evaluator/score.py --export
"""

from __future__ import annotations

import argparse
import os

from metrics import (
    RATERS,
    RATER_LABELS,
    analyse_task,
    read_rows,
    write_methods,
)
from serve import OUT_DIR, discover_tasks


RULE = "-" * 78


def percent(value):
    return "not available" if value is None else "%.1f%%" % (value * 100)


def interval(value):
    if not value:
        return ""
    return " (95%% Wilson CI %.1f%% to %.1f%%)" % (value[0] * 100, value[1] * 100)


def report_group(group):
    print("")
    print("Population: %s" % group["population_label"])
    print("  population N        : %s" % format(group["population_N"], ","))
    print("  sample target       : %s" % group["sample_n"])
    print("  n judged            : %d" % group["n_judged"])
    print("  skipped, still open : %d" % group["n_skipped"])
    print("  rejected            : %d%s" % (
        group["n_rejected"],
        (" (%s%s)" % (percent(group["rejection_rate"]), interval(group["rejection_ci"])))
        if group["n_judged"] else "",
    ))
    print("  cannot tell         : %d (excluded from agreement)" % group["n_cannot_tell"])
    print("  agreement denominator: %d" % group["n_usable"])
    if group["agreement"] is None:
        print("  raw agreement       : not available")
    else:
        print("  raw agreement       : %s (%d of %d)%s" % (
            percent(group["agreement"]), group["n_agree"], group["n_usable"],
            interval(group["agreement_ci"]),
        ))
    if group["kappa"] is not None:
        print("  Cohen's kappa       : %.3f" % group["kappa"])

    if group["reasons"]:
        print("  rejection reasons:")
        for reason, count in sorted(group["reasons"].items(), key=lambda pair: (-pair[1], pair[0])):
            print("    %-58s %d" % (reason, count))

    if group["confusion"]:
        print("  machine label -> human label:")
        for (assigned, human), count in sorted(
            group["confusion"].items(), key=lambda pair: (-pair[1], pair[0])
        ):
            print("    %-30s -> %-30s %d" % (assigned, human, count))

    kappa = "not calculated" if group["kappa"] is None else "%.2f" % group["kappa"]
    judged_noun = "project" if group["n_judged"] == 1 else "projects"
    rejected_clause = (
        "1 project was rejected"
        if group["n_rejected"] == 1
        else "%d projects were rejected" % group["n_rejected"]
    )
    sentence = (
        "For %s, %d %s were judged. Raw human-machine agreement was %s%s, "
        "Cohen's kappa was %s, and %s (%s%s)."
        % (
            group["population_label"],
            group["n_judged"],
            judged_noun,
            percent(group["agreement"]),
            interval(group["agreement_ci"]),
            kappa,
            rejected_clause,
            percent(group["rejection_rate"]),
            interval(group["rejection_ci"]),
        )
    )
    print("  For the paper:")
    print("    " + sentence)
    return sentence


def report_task(task, rater_id):
    path = os.path.join(OUT_DIR, task["task_id"] + ".csv")
    rows = read_rows(path)
    analysis = analyse_task(task, rows, rater_id)
    print("")
    print(RULE)
    print("TASK: %s | %s" % (task["title"], RATER_LABELS[rater_id]))
    print("file: %s" % path)
    print(RULE)
    if not rows:
        print("No judgements yet.")
        return []
    sentences = [report_group(group) for group in analysis["groups"]]
    if analysis["orphans"]:
        print("")
        print("  Preserved legacy rows outside the current reproducible sample: %d" % analysis["orphans"])
    return sentences



def main():
    parser = argparse.ArgumentParser(description="Score blind human validation judgements")
    parser.add_argument("tasks", nargs="*", help="optional task ids")
    parser.add_argument("--rater", choices=RATERS + ("all",), default="primary")
    parser.add_argument("--export", action="store_true", help="write a paste-ready methods paragraph")
    args = parser.parse_args()

    tasks, problems = discover_tasks()
    if args.tasks:
        wanted = set(args.tasks)
        tasks = [task for task in tasks if task["task_id"] in wanted]
    if not tasks:
        print("No matching task files.")
        return
    for problem in problems:
        print("Task warning: %s" % problem)

    raters = RATERS if args.rater == "all" else (args.rater,)
    summary = []
    for rater_id in raters:
        for task in tasks:
            summary.extend(report_task(task, rater_id))

    print("")
    print(RULE)
    print("PASTE-READY RESULT SENTENCES")
    print(RULE)
    if summary:
        for sentence in summary:
            print(sentence)
    else:
        print("No completed judgements yet.")

    if args.export:
        export_rater = "primary" if args.rater == "all" else args.rater
        path = write_methods(tasks, OUT_DIR, export_rater)
        print("")
        print("Methods paragraph written to %s" % path)


if __name__ == "__main__":
    main()
