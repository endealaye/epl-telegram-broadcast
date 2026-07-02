---
description: Run news, fixture, and score agents in a continuous loop
agent: code
---
Run the fetch agents in a loop.

Loop structure:
- Iteration 1: Run `@news-fetcher` agent with prompt "Fetch and filter news now"
- Iteration 2: Run `@fixture-fetcher` agent with prompt "Fetch fixtures now"
- Iteration 3: Run `@score-fetcher` agent with prompt "Fetch scores and live updates now"

Use `$ARGUMENTS` as the number of full cycles (default: 1). For example: `/run-fetch-loop 3` runs the cycle 3 times.

For continuous background looping (daemon mode), use the Python runner instead:
    python3 run_fetch_loop.py [--iterations N | --forever] [--sleep 300]

Between each agent invocation within a cycle, briefly summarize the previous result before moving to the next agent.

At the end, print a combined summary of results for all cycles.
