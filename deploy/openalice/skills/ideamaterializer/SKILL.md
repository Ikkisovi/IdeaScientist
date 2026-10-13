---
name: ideamaterializer
description: Turn an Astra-surviving IdeaScientist proposal into a reviewed script and a CPU/memory/time-bounded offline experiment on read-only factor panels.
---

# IdeaMaterializer

Read `docs/ideamaterializer.md` for the admission contract, scope and label schema,
resource limits and commands. Use `scripts/ideamaterializer/materialize.py` with
a complete IdeaScientist run, selected surviving candidate and hash-bound scope.
Use the OpenAlice host venv. Keep runtime artifacts outside Git. Missing scientific
inputs or a rejected script must leave a readable disposition; do not invent
labels, bypass review, change source datasets or promote execution to acceptance.
