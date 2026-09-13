#!/usr/bin/env python3
"""Local, blind human-validation app for the folk software census.

Start with ``python3 tools/evaluator/serve.py``. The server uses only Python's
standard library. Every action is appended and fsynced before the browser moves.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from metrics import (
    FINAL_ACTIONS,
    RATERS,
    RATER_LABELS,
    REJECT_REASONS,
    append_row as append_result,
    latest_rows,
    read_rows,
    task_progress,
    write_methods,
)


HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
TASKS_DIR = os.path.join(HERE, "tasks")
APP_HTML = os.path.join(HERE, "app.html")
OUT_DIR = os.path.join(PROJECT_ROOT, "data", "processed", "human_labels")

SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
DEFAULT_PORT = 8765
PORT_TRIES = 11
WRITE_LOCK = threading.Lock()


def _text(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _unescape_twice(value):
    return html.unescape(html.unescape(_text(value)))


class NotATaskFile(Exception):
    pass


def load_task_file(path, fallback_id):
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("top level is not an object")
    if not isinstance(raw.get("items"), list):
        raise NotATaskFile(path)

    task_id = _text(raw.get("task_id")).strip() or fallback_id
    if not SAFE_ID.match(task_id):
        task_id = fallback_id
    options = []
    for option in raw.get("options") or []:
        value = _unescape_twice(option).strip()
        if value and value not in options:
            options.append(value)

    items, seen = [], set()
    for index, entry in enumerate(raw.get("items") or []):
        if not isinstance(entry, dict):
            continue
        item_id = _text(entry.get("id") or entry.get("item_id")).strip()
        if not item_id:
            item_id = "item-%d" % (index + 1)
        if item_id in seen:
            item_id = "%s-%d" % (item_id, index + 1)
        seen.add(item_id)
        fields = {}
        for key, value in (entry.get("fields") or {}).items():
            clean = _unescape_twice(value).strip()
            if clean:
                fields[_text(key).strip()] = clean
        items.append({
            "id": item_id,
            "primary": _unescape_twice(entry.get("primary")).strip() or item_id,
            "assigned": _unescape_twice(entry.get("assigned")).strip(),
            "population": _text(entry.get("population")).strip() or "all",
            "fields": fields,
        })

    return {
        "task_id": task_id,
        "title": _unescape_twice(raw.get("title")).strip() or task_id,
        "question": _unescape_twice(raw.get("question") or raw.get("title")).strip() or task_id,
        "finding": _unescape_twice(raw.get("finding")).strip(),
        "instructions": _unescape_twice(raw.get("instructions")).strip(),
        "sample_note": _unescape_twice(raw.get("sample_note")).strip(),
        "options": options,
        "cannot_tell": _unescape_twice(raw.get("cannot_tell")).strip(),
        "sampling": raw.get("sampling") if isinstance(raw.get("sampling"), dict) else {},
        "scoring": raw.get("scoring") if isinstance(raw.get("scoring"), dict) else {},
        "items": items,
    }


def discover_tasks():
    tasks, problems, claimed = [], [], {}
    if not os.path.isdir(TASKS_DIR):
        return tasks, problems
    for name in sorted(os.listdir(TASKS_DIR)):
        if not name.lower().endswith(".json") or name.startswith("."):
            continue
        path = os.path.join(TASKS_DIR, name)
        stem = os.path.splitext(name)[0]
        fallback = stem if SAFE_ID.match(stem) else re.sub(r"[^A-Za-z0-9._-]", "_", stem)
        try:
            task = load_task_file(path, fallback)
        except NotATaskFile:
            continue
        except Exception as exc:
            problems.append("%s could not be read: %s" % (name, exc))
            continue
        if task["task_id"] in claimed:
            problems.append("%s duplicates task id %s" % (name, task["task_id"]))
            continue
        claimed[task["task_id"]] = name
        task["source_file"] = name
        tasks.append(task)
    return tasks, problems


def get_task(task_id):
    return next((task for task in discover_tasks()[0] if task["task_id"] == task_id), None)


def csv_path(task_id):
    return os.path.join(OUT_DIR, "%s.csv" % task_id)


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def valid_rater(value):
    value = _text(value).strip().lower()
    return value if value in RATERS else "primary"


def judged_map(task_id, rater_id):
    out = {}
    for item_id, row in latest_rows(read_rows(csv_path(task_id)), rater_id).items():
        if row["verdict"] in FINAL_ACTIONS:
            out[item_id] = {
                "verdict": row["verdict"],
                "human_label": row["human_label"],
                "belongs": row["belongs"],
                "reject_reason": row["reject_reason"],
                "reject_other": row["reject_other"],
                "note": row["note"],
                "judged_utc": row["judged_utc"],
            }
    return out


def task_summary(task, rater_id):
    rows = read_rows(csv_path(task["task_id"]))
    summary = task_progress(task, rows, rater_id)
    latest = latest_rows(rows, rater_id)
    resume = len(task["items"])
    for index, item in enumerate(task["items"]):
        if latest.get(item["id"], {}).get("verdict") not in FINAL_ACTIONS:
            resume = index
            break
    summary.update({
        "task_id": task["task_id"],
        "title": task["title"],
        "finding": task["finding"],
        "sample_note": task["sample_note"],
        "resume_index": resume,
        "csv_path": csv_path(task["task_id"]),
        "rater_id": rater_id,
        "rater_label": RATER_LABELS[rater_id],
    })
    return summary


def public_task(task, rater_id):
    """Return the browser payload, deliberately omitting assigned/population."""
    summary = task_summary(task, rater_id)
    payload = {
        "ok": True,
        "task_id": task["task_id"],
        "title": task["title"],
        "question": task["question"],
        "finding": task["finding"],
        "instructions": task["instructions"],
        "vocabulary_note": _unescape_twice(task["sampling"].get("vocabulary_note")).strip(),
        "sample_note": task["sample_note"],
        "options": task["options"],
        "items": [
            {"id": item["id"], "primary": item["primary"], "fields": item["fields"]}
            for item in task["items"]
        ],
        "judged": judged_map(task["task_id"], rater_id),
        "reject_reasons": list(REJECT_REASONS),
    }
    payload.update(summary)
    return payload


def methods_task(task, rater_id):
    """Return source-file methods fields and blind-safe live result counts."""
    rows = read_rows(csv_path(task["task_id"]))
    latest = latest_rows(rows, rater_id)
    item_ids = {item["id"] for item in task["items"]}
    current = {
        item_id: row for item_id, row in latest.items()
        if item_id in item_ids and row["verdict"] in FINAL_ACTIONS
    }
    cannot_tell = task["cannot_tell"].casefold()
    reason_counts = {}
    n_cannot_tell = 0
    for row in current.values():
        if (
            row["verdict"] == "label"
            and cannot_tell
            and row["human_label"].casefold() == cannot_tell
        ):
            n_cannot_tell += 1
        if row["verdict"] == "reject":
            reason = row["reject_reason"] or "Reason not recorded"
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {
        "task_id": task["task_id"],
        "title": task["title"],
        "sampling": task["sampling"],
        "n_cannot_tell": n_cannot_tell,
        "reject_reason_counts": reason_counts,
    }


def append_action(task, item, rater_id, verdict, **values):
    row = {
        "item_id": item["id"],
        "rater_id": rater_id,
        "assigned": item["assigned"],
        "verdict": verdict,
        "human_label": values.get("human_label", ""),
        "corrected_label": "",
        "belongs": values.get("belongs", ""),
        "reject_reason": values.get("reject_reason", ""),
        "reject_other": values.get("reject_other", ""),
        "note": values.get("note", ""),
        "judged_utc": now_utc(),
    }
    with WRITE_LOCK:
        append_result(csv_path(task["task_id"]), row)


def undo_last(task, rater_id):
    rows = read_rows(csv_path(task["task_id"]))
    latest = latest_rows(rows, rater_id)
    for row in reversed(rows):
        if row["rater_id"] != rater_id:
            continue
        if latest.get(row["item_id"]) is not row:
            continue
        if row["verdict"] not in FINAL_ACTIONS:
            continue
        item = next((one for one in task["items"] if one["id"] == row["item_id"]), None)
        if item:
            append_action(task, item, rater_id, "undo", note="Undo")
            return item["id"]
    return None


def esc(value):
    return html.escape(str(value), quote=True)


MENU_CSS = """
:root { color-scheme:light; --paper:#f6f7f7; --cream:#faf0e1; --panel:#fff; --ink:#202020;
  --charcoal:#37424a; --dim:#565d60; --line:#bfc3c4; --gold:#ffcd6e; --gold-soft:#fff1cf;
  --blue:#3255c3; --periwinkle:#91a7d2; --danger:#a61736; --focus:#1d4ed8; }
* { box-sizing:border-box; }
html { scroll-behavior:smooth; }
body { margin:0; min-height:100vh; background:linear-gradient(90deg,var(--gold) 0 12px,transparent 12px),var(--paper);
  color:var(--ink); font:16px/1.5 Arial,Helvetica,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; -webkit-font-smoothing:antialiased; }
a,button { -webkit-tap-highlight-color:transparent; }
:focus-visible { outline:3px solid var(--focus); outline-offset:3px; }
.skip { position:fixed; z-index:10; top:8px; left:24px; padding:10px 14px; color:var(--ink); background:var(--gold);
  border:2px solid var(--ink); font-weight:800; transform:translateY(-150%); }
.skip:focus { transform:translateY(0); }
.wrap { width:min(1040px,calc(100% - 48px)); margin:auto; padding:36px 0 68px; }
header { margin-bottom:32px; }
.institution { display:flex; justify-content:space-between; align-items:center; gap:20px; margin-bottom:48px; padding-bottom:13px;
  border-bottom:1px solid var(--ink); color:var(--ink); font-size:13px; font-weight:700; }
.institution span { color:var(--dim); font-size:11px; font-weight:800; letter-spacing:.09em; text-transform:uppercase; }
.hero { display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:end; gap:36px; }
.eyebrow { color:var(--dim); text-transform:uppercase; letter-spacing:.12em; font-size:11px; font-weight:800; }
h1 { margin:7px 0 10px; font-family:"Arial Narrow","Aptos Narrow",Arial,Helvetica,sans-serif; font-size:clamp(42px,7vw,76px);
  font-stretch:condensed; font-weight:900; line-height:.95; letter-spacing:-.055em; }
h1 span { display:inline-block; margin-left:.04em; padding:2px 10px 6px 7px; background:var(--gold); }
.sub { color:var(--dim); margin:0; max-width:61ch; font-size:17px; }
.rater-wrap { text-align:right; }
.rater-label { display:block; margin-bottom:6px; color:var(--dim); font-size:11px; font-weight:800; letter-spacing:.1em; text-transform:uppercase; }
.raters { display:flex; border:1px solid var(--ink); background:var(--panel); white-space:nowrap; }
.raters a { min-height:44px; display:inline-flex; align-items:center; color:var(--ink); text-decoration:none; padding:9px 13px; font-size:14px; }
.raters a + a { border-left:1px solid var(--ink); }
.raters a:hover { background:var(--gold-soft); }
.raters a.on { color:#fff; background:var(--ink); font-weight:700; }
.notice { padding:13px 15px; border:1px solid var(--danger); background:#fff0f3; color:#7d102a; margin:0 0 16px; }
.tasks-heading { margin:0 0 10px; color:var(--dim); font-size:11px; font-weight:800; letter-spacing:.1em; text-transform:uppercase; }
.tasks { display:grid; gap:12px; }
.card { position:relative; display:block; overflow:hidden; color:inherit; text-decoration:none; border:1px solid var(--ink); background:var(--panel); padding:21px 22px 17px; transition:background .12s ease; }
.card::after { content:""; position:absolute; top:0; right:0; width:11px; height:100%; background:var(--periwinkle); transform:translateX(8px); transition:transform .12s ease; }
.card:hover { background:var(--gold-soft); }
.card:hover::after,.card:focus-visible::after { transform:translateX(0); }
.cardtop,.stats { display:flex; align-items:baseline; justify-content:space-between; gap:18px; }
.name { max-width:80%; font-size:22px; font-weight:800; letter-spacing:-.02em; }
.status { color:var(--blue); font-weight:800; font-size:13px; text-decoration:underline; text-underline-offset:3px; }
.finding { color:var(--dim); margin:5px 0 18px; max-width:67ch; }
.bar { height:8px; overflow:hidden; background:#e1e3e3; border:1px solid var(--line); }
.fill { height:100%; background:var(--periwinkle); }
.stats { color:var(--dim); font-size:13px; margin-top:9px; font-variant-numeric:tabular-nums; }
.stats strong { color:var(--ink); }
.footer { margin-top:30px; display:flex; align-items:center; justify-content:space-between; gap:22px; padding:23px 0 0; border-top:1px solid var(--ink); }
.method { color:var(--dim); font-size:14px; max-width:61ch; }
.method strong { display:block; margin-bottom:3px; color:var(--ink); font-size:13px; letter-spacing:.04em; }
button { min-height:44px; border:1px solid var(--ink); background:var(--ink); color:#fff; padding:10px 14px; border-radius:2px; font:inherit; font-weight:700; cursor:pointer; }
button:hover { color:var(--ink); background:var(--gold); }
button:disabled { opacity:.55; cursor:wait; }
#exportmsg { color:var(--dim); font-size:13px; text-align:right; margin-top:7px; }
@media (max-width:700px) { body{background:linear-gradient(90deg,var(--gold) 0 6px,transparent 6px),var(--paper)} .wrap{width:min(100% - 28px,1040px);padding-top:22px}
  .institution{align-items:flex-start;flex-direction:column;gap:2px;margin-bottom:30px}.hero{grid-template-columns:1fr;align-items:start;gap:24px}.rater-wrap{text-align:left}
  .footer{align-items:flex-start;flex-direction:column}.cardtop,.stats{align-items:flex-start}.stats{flex-direction:column;gap:3px}.name{max-width:none}h1 span{margin-left:0} }
@media (prefers-reduced-motion:reduce) { html{scroll-behavior:auto} *,*::before,*::after{animation-duration:.01ms!important;transition-duration:.01ms!important} }
"""


def render_menu(rater_id, problems):
    tasks, discovered_problems = discover_tasks()
    problems = problems + discovered_problems
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<meta name='theme-color' content='#202020'><meta name='color-scheme' content='light'><link rel='icon' href='/favicon.svg'>",
        "<title>Software labeling study</title><style>%s</style></head><body><a class='skip' href='#tasks'>Skip to tasks</a><main class='wrap'>" % MENU_CSS,
        "<header><div class='institution'>Goldsmiths, University of London <span>MSc Data Science research</span></div>",
        "<div class='hero'><div><div class='eyebrow'>Human evaluation instrument</div><h1>Folk software <span>validation</span></h1>",
        "<p class='sub'>Choose a task. Each answer saves immediately. Machine labels stay hidden until scoring.</p></div>",
    ]
    parts.append("</div></header>")
    for problem in problems:
        parts.append("<div class='notice'>%s</div>" % esc(problem))
    parts.append("<h2 id='tasks' class='tasks-heading'>Validation tasks</h2><section class='tasks' aria-labelledby='tasks'>")
    for task in tasks:
        summary = task_summary(task, rater_id)
        total, done = summary["n_items"], summary["n_judged"]
        pct = 100 * done / total if total else 0
        left = max(0, total - done)
        minutes = max(1, round(left * 14 / 60)) if left else 0
        status = "Complete" if left == 0 else ("Resume" if done else "Start")
        margin = summary["widest_margin"]
        margin_copy = (
            "Widest current 95%% margin: <strong>±%.1f points</strong>" % (margin * 100)
            if margin is not None else "Margin appears once enough judgements are saved"
        )
        parts.append(
            "<a class='card' href='/t/%s?rater=%s'><div class='cardtop'><div class='name'>%s</div>"
            "<div class='status'>%s</div></div><p class='finding'>%s</p>"
            "<div class='bar' role='progressbar' aria-label='%s progress' aria-valuemin='0' aria-valuemax='100' aria-valuenow='%.0f'><div class='fill' style='width:%.2f%%'></div></div>"
            "<div class='stats'><span><strong>%d</strong> of %d judged · %d rejected · %d skipped</span>"
            "<span>%s%s</span></div></a>"
            % (
                esc(task["task_id"]), rater_id, esc(task["title"]), status,
                esc(task["finding"] or task["sample_note"]), esc(task["title"]), pct, pct, done, total,
                summary["n_rejected"], summary["n_skipped"], margin_copy,
                (" · about %d min left" % minutes) if minutes else "",
            )
        )
    if not tasks:
        parts.append("<div class='notice'>No task files were found.</div>")
    parts.append("</section><div class='footer'><div class='method'><strong>Measurement design</strong>Sample sizes use the finite population correction. Results use Wilson intervals and keep the two genre populations separate. <a href='/methods?rater=%s'>View full methods and live progress</a>.</div>" % rater_id)
    parts.append("<div><button id='export' type='button'>Export %s methods paragraph</button><div id='exportmsg' role='status' aria-live='polite'></div></div></div>" % esc(RATER_LABELS[rater_id].lower()))
    parts.append("<script>document.getElementById('export').onclick=function(){var b=this,m=document.getElementById('exportmsg');b.disabled=true;m.textContent='Writing...';fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rater_id:'%s'})}).then(function(r){return r.json()}).then(function(x){if(!x.ok)throw Error(x.error||'Could not export');m.textContent='Saved to '+x.saved_to}).catch(function(e){m.textContent=e.message}).finally(function(){b.disabled=false})}</script>" % rater_id)
    parts.append("</main></body></html>")
    return "".join(parts)


class Handler(BaseHTTPRequestHandler):
    server_version = "folk-evaluator/2.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, content_type):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; frame-src http: https:; img-src 'self' data:; frame-ancestors 'none'",
        )
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload, code=200):
        self._send(code, json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")

    def _html(self, markup, code=200):
        self._send(code, markup, "text/html; charset=utf-8")

    def _error(self, code, message):
        self._json({"ok": False, "error": message}, code)

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length <= 0 or length > 64_000:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        try:
            if path == "/":
                return self._html(render_menu(valid_rater((query.get("rater") or [""])[0]), []))
            if path == "/methods":
                with open(APP_HTML, "r", encoding="utf-8") as handle:
                    return self._html(handle.read())
            if path == "/favicon.svg":
                icon = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='7' fill='%23071018'/><path d='M7 16h6l3-7 3 14 3-7h3' fill='none' stroke='%2345ddb6' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/></svg>"
                return self._send(200, icon, "image/svg+xml")
            if path.startswith("/t/"):
                task_id = path[3:].strip("/")
                if not SAFE_ID.match(task_id) or get_task(task_id) is None:
                    return self._html("<p>Unknown task. <a href='/'>Back to tasks</a></p>", 404)
                with open(APP_HTML, "r", encoding="utf-8") as handle:
                    return self._html(handle.read())
            if path == "/api/tasks":
                rater = valid_rater((query.get("rater") or [""])[0])
                tasks, problems = discover_tasks()
                return self._json({"ok": True, "tasks": [task_summary(t, rater) for t in tasks], "problems": problems})
            if path == "/api/methods":
                rater = valid_rater((query.get("rater") or [""])[0])
                tasks, problems = discover_tasks()
                return self._json({"ok": True, "tasks": [methods_task(t, rater) for t in tasks], "problems": problems})
            if path.startswith("/api/task/"):
                task_id = path[len("/api/task/"):].strip("/")
                rater = valid_rater((query.get("rater") or [""])[0])
                task = get_task(task_id) if SAFE_ID.match(task_id) else None
                if task is None:
                    return self._error(404, "unknown task")
                return self._json(public_task(task, rater))
            return self._html("<p>Not found. <a href='/'>Back to tasks</a></p>", 404)
        except BrokenPipeError:
            pass
        except Exception as exc:
            sys.stderr.write("GET %s failed: %s\n" % (path, exc))
            try:
                self._error(500, "The evaluator hit an internal error")
            except Exception:
                pass

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        path = unquote(urlparse(self.path).path)
        try:
            payload = self._body()
            if payload is None:
                return self._error(400, "body was not JSON")
            rater_id = valid_rater(payload.get("rater_id"))
            if path == "/api/export":
                tasks, _ = discover_tasks()
                written = write_methods(tasks, OUT_DIR, rater_id)
                return self._json({"ok": True, "saved_to": written})

            task_id = _text(payload.get("task_id")).strip()
            task = get_task(task_id) if SAFE_ID.match(task_id) else None
            if task is None:
                return self._error(404, "unknown task")
            if path == "/api/undo":
                item_id = undo_last(task, rater_id)
                summary = task_summary(task, rater_id)
                summary.update({
                    "ok": item_id is not None,
                    "item_id": item_id or "",
                    "index": next((i for i, item in enumerate(task["items"]) if item["id"] == item_id), -1),
                })
                if item_id is None:
                    summary["error"] = "Nothing to undo"
                return self._json(summary)
            if path != "/api/judge":
                return self._error(404, "unknown endpoint")

            item_id = _text(payload.get("item_id")).strip()
            item = next((one for one in task["items"] if one["id"] == item_id), None)
            if item is None:
                return self._error(400, "unknown item")
            verdict = _text(payload.get("verdict")).strip().lower()
            note = " ".join(_text(payload.get("note")).split())[:1000]
            if verdict == "label":
                human_label = _unescape_twice(payload.get("human_label")).strip()
                if human_label not in task["options"]:
                    return self._error(400, "choose one of the task's fixed answers")
                append_action(task, item, rater_id, "label", human_label=human_label, belongs="yes", note=note)
            elif verdict == "reject":
                reason = _unescape_twice(payload.get("reject_reason")).strip()
                other = " ".join(_text(payload.get("reject_other")).split())[:500]
                if reason not in REJECT_REASONS:
                    return self._error(400, "choose a fixed rejection reason")
                if reason == "Other" and not other:
                    return self._error(400, "say why this item does not belong")
                append_action(task, item, rater_id, "reject", belongs="no", reject_reason=reason, reject_other=other, note=note)
            elif verdict == "skip":
                append_action(task, item, rater_id, "skip", note=note)
            else:
                return self._error(400, "verdict must be label, reject, or skip")

            summary = task_summary(task, rater_id)
            summary.update({
                "ok": True,
                "item_id": item["id"],
                "verdict": verdict,
                "human_label": payload.get("human_label", "") if verdict == "label" else "",
                "reject_reason": payload.get("reject_reason", "") if verdict == "reject" else "",
                "note": note,
            })
            return self._json(summary)
        except BrokenPipeError:
            pass
        except Exception as exc:
            sys.stderr.write("POST %s failed: %s\n" % (path, exc))
            try:
                self._error(500, "The judgement was not saved")
            except Exception:
                pass


def start(preferred_port):
    last_error = None
    for port in range(preferred_port, preferred_port + PORT_TRIES):
        try:
            return ThreadingHTTPServer(("127.0.0.1", port), Handler), port
        except OSError as exc:
            last_error = exc
    raise SystemExit("No free local port from %d to %d: %s" % (
        preferred_port, preferred_port + PORT_TRIES - 1, last_error
    ))


def main():
    parser = argparse.ArgumentParser(description="Blind local validation app")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="first local port to try")
    args = parser.parse_args()
    os.makedirs(TASKS_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    if not os.path.exists(APP_HTML):
        raise SystemExit("Missing %s" % APP_HTML)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    httpd, port = start(args.port)
    print("Evaluator ready at http://127.0.0.1:%d/" % port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("Stopped. Saved judgements are already on disk.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
