"""Smoke check for the semantic layer, run by semantic/.venv's interpreter
(the MCP SDK needs Python >=3.10; the root interpreter cannot import it).

Imports semantic/server.py the way the dashboard does (as a file, not a
package), then confirms the three public tools answer against the built
marts: the whitelist lists every registry metric, a definition resolves, and
one computable Layer-1 metric returns rows with no error payload.
"""
import importlib.util
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    spec = importlib.util.spec_from_file_location(
        "acme_semantic_server", os.path.join(REPO_ROOT, "semantic", "server.py"))
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)

    with open(os.path.join(REPO_ROOT, "semantic", "metric_registry.json")) as f:
        registry = json.load(f)

    listed = server.list_metrics()
    problems = []
    if listed["count"] != len(registry["metric_order"]):
        problems.append(f"list_metrics returned {listed['count']} metrics, "
                        f"registry has {len(registry['metric_order'])}")

    computable = [m for m in listed["metrics"] if m["computable"] and m["layer"] == 1]
    if not computable:
        problems.append("no computable Layer-1 metric in the registry")
    else:
        key = computable[0]["key"]
        definition = server.get_metric_definition(key)
        if "error" in definition:
            problems.append(f"get_metric_definition({key}) -> {definition['error']}")
        result = server.query_metric(key, grain="year")
        if "error" in result:
            problems.append(f"query_metric({key}) -> {result['error']}: {result.get('message')}")
        elif not result["data"]:
            problems.append(f"query_metric({key}) returned no rows")
        else:
            print(f"query_metric({key}, grain=year): {len(result['data'])} rows")

    rejected = server.query_metric("definitely_not_a_metric")
    if "error" not in rejected:
        problems.append("the whitelist accepted an unknown metric name")

    print(f"list_metrics: {listed['count']} metrics, "
          f"{sum(1 for m in listed['metrics'] if m['computable'])} computable")
    for p in problems:
        print(f"[FAIL] {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
