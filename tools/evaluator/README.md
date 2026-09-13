# Folk software evaluator

The evaluator presents one project and a fixed set of answers at a time.
The judge can inspect the available evidence while the model answer remains
hidden. A saved response advances to the next project.

The completed study used one rater. The interface reads local tasks from
`tools/evaluator/tasks/` and appends events to
`data/processed/human_labels/`. Those working files contain private evidence
links and notes. The submission instead includes the final label snapshot
under `data/processed/alignment/`.

With local task files available, start the interface using system Python.
It has no additional Python dependencies.

```sh
python3 tools/evaluator/serve.py
```

Open the local address printed by the server. Number and letter keys select
answers. `R` records a rejection with a reason, `S` skips an item, `Z` undoes
the last judgment and `N` adds a note. Each event is flushed to disk before
the page advances. Reopening resumes at the first unjudged item.

`tools/evaluator/score.py` scores local event files. The submitted notebook
reproduces the completed evaluation from the frozen public files, using
`src/alignment_history.py`.
