"""Orchestration layer: the task DAG, node selection, the runner, and the
guards that keep the DAG and the freshness contract aligned with the code
they describe (a new analytics module or generator batch that is not wired
into the DAG fails here).

Reads source files and runs only no-op subprocesses; needs neither data/raw
nor the dbt database, so it is the first QA gate in the pipeline.
"""
import glob
import json
import os
import re
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import cli, runner  # noqa: E402
from pipeline.dag import DagError, Node, Selection, select, topological_order, validate  # noqa: E402
from pipeline.freshness import load_contract  # noqa: E402
from pipeline.nodes import ANALYTICS_ALL, BY_NAME, GENERATOR_NODES, NODES  # noqa: E402

REPO = runner.REPO_ROOT


def _n(name, deps=(), **kw):
    return Node(name=name, kind="qa", description=name,
                argv=("{python}", "-c", "pass"), deps=tuple(deps), **kw)


def _names(sel):
    return [n.name for n in sel.order]


# --------------------------------------------------------------------------
# graph validity
# --------------------------------------------------------------------------

class TestGraphValidity:
    def test_declared_graph_is_valid_and_acyclic(self):
        validate(NODES)
        order = [n.name for n in topological_order(NODES)]
        assert len(order) == len(NODES) == len(set(order))

    def test_every_dependency_precedes_its_dependent(self):
        pos = {n.name: i for i, n in enumerate(topological_order(NODES))}
        for n in NODES:
            for d in n.deps:
                assert pos[d] < pos[n.name], f"{n.name} scheduled before its dependency {d}"

    def test_cycle_is_rejected(self):
        with pytest.raises(DagError, match="cycle"):
            validate([_n("a", ["c"]), _n("b", ["a"]), _n("c", ["b"])])

    def test_unknown_dependency_is_rejected(self):
        with pytest.raises(DagError, match="unknown node"):
            validate([_n("a", ["ghost"])])

    def test_duplicate_name_is_rejected(self):
        with pytest.raises(DagError, match="duplicate"):
            validate([_n("a"), _n("a")])

    def test_opt_in_node_cannot_depend_on_regular_node(self):
        with pytest.raises(DagError, match="opt-in"):
            validate([_n("a"), _n("g", ["a"], opt_in=True, profiles=frozenset({"rebuild"}))])

    def test_ordering_is_deterministic(self):
        assert [n.name for n in topological_order(NODES)] == \
               [n.name for n in topological_order(NODES)]


# --------------------------------------------------------------------------
# the real graph's shape
# --------------------------------------------------------------------------

class TestRealGraph:
    def test_default_selection_excludes_generators(self):
        sel = select(NODES)
        assert not any(n.opt_in for n in sel.order)
        assert _names(sel)[0] == "qa_pipeline"

    def test_with_generators_runs_them_first_in_dependency_order(self):
        names = _names(select(NODES, with_generators=True))
        gens = [n.name for n in GENERATOR_NODES]
        assert set(gens) <= set(names)
        assert max(names.index(g) for g in gens) < names.index("qa_raw")
        assert names.index("gen_foundation") < names.index("gen_batch2") < names.index("gen_batch3")

    def test_quality_gates_precede_analytics_and_analytics_precede_refresh(self):
        names = _names(select(NODES))
        for a in ANALYTICS_ALL:
            assert names.index("governance_gate") < names.index(a.name) < names.index("dbt_refresh_logs")
        assert names.index("qa_raw") < names.index("dbt_build") < names.index("governance_gate")

    def test_proxy_metric_health_runs_after_every_other_analytics_artifact(self):
        names = _names(select(NODES))
        for a in ANALYTICS_ALL:
            if a.name != "proxy_metric_health":
                assert names.index(a.name) < names.index("proxy_metric_health")

    def test_log_writers_precede_their_readers(self):
        names = _names(select(NODES))
        # weekly_readout reads data/playbook_triggers.csv and runs the variance engine
        assert names.index("playbook_triggers") < names.index("weekly_readout")
        assert names.index("variance_diagnostic") < names.index("weekly_readout")
        # variance_diagnostic imports marketing_attribution's pipeline_generated node
        assert names.index("marketing_attribution") < names.index("variance_diagnostic")
        assert names.index("variance_diagnostic") < names.index("scenario_planning")
        assert names.index("weekly_readout") < names.index("dashboard_smoke")

    def test_ci_profile_is_the_fast_verification_subset(self):
        names = _names(select(NODES, profile="ci"))
        assert names == ["qa_pipeline", "qa_raw", "dbt_build", "qa_marts",
                         "governance_gate", "registry_check", "freshness_check"]

    def test_monitor_profile_is_empty_until_a_monitor_node_is_registered(self):
        with pytest.raises(DagError, match="selects no nodes"):
            select(NODES, profile="monitor")

    def test_venv_nodes_declare_their_interpreter(self):
        assert BY_NAME["semantic_smoke"].interpreter == "semantic"
        assert BY_NAME["dashboard_smoke"].interpreter == "dashboard"
        assert all(n.interpreter == "root" for n in NODES
                   if n.name not in ("semantic_smoke", "dashboard_smoke"))


# --------------------------------------------------------------------------
# selection flags
# --------------------------------------------------------------------------

class TestSelection:
    def test_only_includes_required_upstream_but_never_generators(self):
        names = _names(select(NODES, only=["weekly_readout"]))
        for required in ("qa_raw", "dbt_build", "governance_gate", "variance_diagnostic",
                         "playbook_triggers", "health_score", "marketing_attribution"):
            assert required in names
        assert "proxy_metric_health" not in names
        assert not any(n.startswith("gen_") for n in names)
        assert names[-1] == "weekly_readout"

    def test_only_no_deps_runs_exactly_the_named_node(self):
        assert _names(select(NODES, only=["forecast"], with_deps=False)) == ["forecast"]

    def test_naming_a_generator_pulls_in_its_upstream_generators(self):
        names = _names(select(NODES, only=["gen_batch3"]))
        assert names == ["gen_foundation", "gen_batch2", "gen_batch3"]

    def test_from_selects_the_node_and_everything_downstream(self):
        names = _names(select(NODES, from_=["variance_diagnostic"]))
        assert {"variance_diagnostic", "scenario_planning", "weekly_readout",
                "proxy_metric_health", "dbt_refresh_logs", "freshness_check"} <= set(names)
        assert "health_score" not in names and "dbt_build" not in names

    def test_from_a_generator_regenerates_its_dependents_only(self):
        names = _names(select(NODES, from_=["gen_batch7"]))
        assert {"gen_batch7", "gen_batch11", "gen_batch12", "qa_raw", "dbt_build"} <= set(names)
        assert "gen_batch2" not in names and "gen_batch9" not in names

    def test_unknown_node_is_a_reported_error(self):
        with pytest.raises(DagError, match="unknown node"):
            select(NODES, only=["nope"])
        with pytest.raises(DagError, match="unknown node"):
            select(NODES, from_=["nope"])

    def test_plan_and_dry_run_have_no_side_effects(self, monkeypatch, tmp_path, capsys):
        def boom(*a, **k):
            raise AssertionError("a subprocess was started")
        monkeypatch.setattr(runner.subprocess, "run", boom)
        monkeypatch.setattr(runner, "RUNS_DIR", str(tmp_path / "runs"))
        assert cli.main(["plan"]) == 0
        assert cli.main(["run", "--dry-run", "--with-generators"]) == 0
        assert cli.main(["plan", "--json", "--only", "weekly_readout"]) == 0
        assert not (tmp_path / "runs").exists()
        out = capsys.readouterr().out
        assert "weekly_readout" in out and "gen_foundation" in out

    def test_invalid_selection_exits_2(self, capsys):
        assert cli.main(["plan", "--only", "nope"]) == runner.EXIT_USAGE
        assert "unknown node" in capsys.readouterr().err


# --------------------------------------------------------------------------
# runner behaviour on synthetic nodes
# --------------------------------------------------------------------------

def _sel(*nodes):
    return Selection(tuple(nodes), "verify", False)


def _py(code):
    return ("{python}", "-c", code)


class TestRunner:
    def test_passing_run_writes_manifest_and_logs(self, tmp_path):
        a = Node("a", "qa", "a", _py("print('hi')"))
        b = Node("b", "qa", "b", _py("pass"), deps=("a",))
        code = runner.execute(_sel(a, b), runs_dir=str(tmp_path))
        assert code == 0
        manifest = json.loads((tmp_path / "latest.json").read_text())
        assert manifest["exit_code"] == 0
        assert [n["name"] for n in manifest["nodes"]] == ["a", "b"]
        assert all(n["status"] == "passed" and n["seconds"] >= 0 for n in manifest["nodes"])
        assert manifest["counts"]["passed"] == 2
        assert (tmp_path / manifest["run_id"] / "a.log").read_text().strip() == "hi"

    def test_fails_fast_and_reports_the_failing_node(self, tmp_path, capsys):
        a = Node("a", "qa", "a", _py("pass"))
        b = Node("b", "qa", "b", _py("import sys; print('boom'); sys.exit(7)"), deps=("a",))
        c = Node("c", "qa", "c", _py("pass"), deps=("b",))
        code = runner.execute(_sel(a, b, c), runs_dir=str(tmp_path))
        assert code == runner.EXIT_NODE_FAILED
        manifest = json.loads((tmp_path / "latest.json").read_text())
        status = {n["name"]: n["status"] for n in manifest["nodes"]}
        assert status == {"a": "passed", "b": "failed", "c": "not_run"}
        assert manifest["nodes"][1]["exit_code"] == 7
        out = capsys.readouterr().out
        assert "FAILED NODE: b" in out and "not run: c" in out and "boom" in out

    def test_printed_fail_marker_fails_a_node_that_exits_zero(self, tmp_path):
        a = Node("a", "analytics", "a", _py("print('[PASS] ok'); print('[FAIL] check x')"),
                 fail_patterns=(r"^\s*\[FAIL\]",))
        assert runner.execute(_sel(a), runs_dir=str(tmp_path)) == runner.EXIT_NODE_FAILED
        manifest = json.loads((tmp_path / "latest.json").read_text())
        assert "failed check" in manifest["nodes"][0]["reason"]

    def test_documented_expected_findings_do_not_fail_a_node(self, tmp_path):
        code = "print('[PASS] a'); print('[FAIL] known_null_finding: p=0.49')"
        ok = Node("a", "analytics", "a", _py(code), fail_patterns=(r"^\s*\[FAIL\]",),
                  expected_fail=(r"^\s*\[FAIL\] known_null_finding:",))
        assert runner.execute(_sel(ok), runs_dir=str(tmp_path)) == runner.EXIT_OK
        other = "print('[FAIL] known_null_finding: x'); print('[FAIL] real_defect: y')"
        bad = Node("a", "analytics", "a", _py(other), fail_patterns=(r"^\s*\[FAIL\]",),
                   expected_fail=(r"^\s*\[FAIL\] known_null_finding:",))
        assert runner.execute(_sel(bad), runs_dir=str(tmp_path)) == runner.EXIT_NODE_FAILED
        manifest = json.loads((tmp_path / "latest.json").read_text())
        assert "real_defect" in manifest["nodes"][0]["reason"]

    def test_missing_venv_is_an_explicit_skip_not_a_pass(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setitem(runner._VENV_PYTHON, "semantic", str(tmp_path / "no" / "python"))
        s = Node("s", "semantic", "s", _py("pass"), interpreter="semantic")
        assert runner.execute(_sel(s), runs_dir=str(tmp_path)) == runner.EXIT_OK
        manifest = json.loads((tmp_path / "latest.json").read_text())
        assert manifest["nodes"][0]["status"] == "skipped"
        assert manifest["nodes"][0]["reason"].startswith("venv missing")
        assert "SKIPPED: s" in capsys.readouterr().out

    def test_strict_turns_a_skip_into_a_failure_exit(self, tmp_path, monkeypatch):
        monkeypatch.setitem(runner._VENV_PYTHON, "dashboard", str(tmp_path / "no" / "python"))
        s = Node("s", "dashboard", "s", _py("pass"), interpreter="dashboard")
        assert runner.execute(_sel(s), strict=True, runs_dir=str(tmp_path)) == runner.EXIT_STRICT_SKIP

    def test_unmet_precondition_fails_with_an_actionable_message(self, tmp_path):
        a = Node("a", "analytics", "a", _py("pass"), requires=("data/acme_gtm.duckdb.nope",))
        assert runner.execute(_sel(a), runs_dir=str(tmp_path)) == runner.EXIT_NODE_FAILED
        manifest = json.loads((tmp_path / "latest.json").read_text())
        assert "precondition" in manifest["nodes"][0]["reason"]

    def test_timeout_fails_the_node(self, tmp_path):
        a = Node("a", "qa", "a", _py("import time; time.sleep(30)"), timeout_s=1)
        assert runner.execute(_sel(a), runs_dir=str(tmp_path)) == runner.EXIT_NODE_FAILED
        manifest = json.loads((tmp_path / "latest.json").read_text())
        assert "timed out" in manifest["nodes"][0]["reason"]

    def test_glob_tokens_expand_to_repo_relative_files(self):
        argv = runner.resolve_argv(BY_NAME["qa_raw"], "PY")
        assert argv[0] == "PY"
        assert "tests/test_phase1_foundation.py" in argv
        assert not any("*" in t for t in argv)


# --------------------------------------------------------------------------
# guards: the DAG and the contract stay aligned with the code
# --------------------------------------------------------------------------

def _analytics_modules():
    return sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(REPO, "analytics", "*.py")))


def _has_main(module):
    with open(os.path.join(REPO, "analytics", f"{module}.py")) as f:
        return re.search(r'^if __name__ == "__main__":', f.read(), re.M) is not None


def _main_block_dates(module):
    with open(os.path.join(REPO, "analytics", f"{module}.py")) as f:
        src = f.read()
    block = src[src.index('if __name__ == "__main__":'):]
    return sorted({date(int(y), int(m), int(d)).isoformat()
                   for y, m, d in re.findall(r"date\((\d{4}),\s*(\d{1,2}),\s*(\d{1,2})\)", block)})


class TestCoverage:
    def test_every_analytics_module_with_a_main_is_a_dag_node_running_that_module(self):
        targets = {}
        for n in ANALYTICS_ALL:
            for i, tok in enumerate(n.argv):
                if tok == "-m" and n.argv[i + 1].startswith("analytics."):
                    targets[n.argv[i + 1].split(".", 1)[1]] = n.name
        for m in _analytics_modules():
            if _has_main(m):
                assert m in targets, (
                    f"analytics/{m}.py has a __main__ but no node in pipeline/nodes.py runs it")

    def test_every_analytics_module_is_in_the_contract_or_declared_a_library(self):
        contract = load_contract()
        covered = {a["module"].split(".", 1)[1] for a in contract["artifacts"] if a.get("module")}
        libraries = {k.split(".", 1)[1] for k in contract["library_modules"]}
        # deal_diagnostics has no __main__ but is an artifact (run via pipeline.entrypoints)
        for m in _analytics_modules():
            assert m in covered | libraries, (
                f"analytics/{m}.py is neither a contracted artifact nor a declared library module")

    def test_every_dag_analytics_node_has_a_contract_entry_and_vice_versa(self):
        contract = load_contract()
        entries = {a["node"] for a in contract["artifacts"] if a["kind"] == "analytics"}
        assert entries == {n.name for n in ANALYTICS_ALL}

    def test_contract_nodes_exist_in_the_dag(self):
        for a in load_contract()["artifacts"]:
            assert a["node"] in BY_NAME, f"{a['name']}: node {a['node']} is not in the DAG"

    def test_contract_checkpoint_dates_match_the_entrypoint_source(self):
        for a in load_contract()["artifacts"]:
            if a["kind"] != "analytics" or not _has_main(a["module"].split(".", 1)[1]):
                continue
            assert sorted(a["entrypoint_as_of"]) == _main_block_dates(a["module"].split(".", 1)[1]), a["name"]
            assert sorted(BY_NAME[a["node"]].as_of) == sorted(a["entrypoint_as_of"]), a["name"]

    def test_contract_model_names_match_the_modules_logged_name(self):
        for a in load_contract()["artifacts"]:
            if a["kind"] != "analytics":
                continue
            with open(os.path.join(REPO, "analytics", a["module"].split(".", 1)[1] + ".py")) as f:
                declared = re.search(r'^_MODEL_NAME = "([^"]+)"', f.read(), re.M).group(1)
            logged = [e["model_name"] for e in a["evidence"] if e["type"] == "perf_log"]
            assert logged == [declared], a["name"]

    def test_contract_dependencies_equal_the_dag_dependencies(self):
        contract = load_contract()
        by_node = {a["node"]: a for a in contract["artifacts"] if a["kind"] == "analytics"}
        for n in ANALYTICS_ALL:
            expected = {"dbt_marts"} | {d for d in n.deps if d not in ("governance_gate", "dbt_build")}
            assert set(by_node[n.name]["depends_on"]) == expected, n.name

    def test_contract_output_globs_match_what_modules_write(self):
        contract = load_contract()
        with_outputs = {a["name"] for a in contract["artifacts"]
                        if any(e["type"] == "output_files" for e in a["evidence"])
                        and a["kind"] == "analytics"}
        writers = set()
        for m in _analytics_modules():
            with open(os.path.join(REPO, "analytics", f"{m}.py")) as f:
                if re.search(r'f"[a-z_]+_\{(?:as_of_date\.isoformat\(\)|stamp)\}\.(json|md)"', f.read()):
                    writers.add(m)
        assert with_outputs == writers

    def test_every_generator_module_is_a_node_and_reads_only_declared_upstream(self):
        modules = sorted(os.path.basename(p)[:-3]
                         for p in glob.glob(os.path.join(REPO, "generators", "run_*.py")))
        by_module = {n.argv[2].split(".", 1)[1]: n for n in GENERATOR_NODES}
        assert set(modules) == set(by_module), "generators/run_*.py and the DAG disagree"

        writes, reads = {}, {}
        for m in modules:
            with open(os.path.join(REPO, "generators", f"{m}.py")) as f:
                lines = f.read().splitlines()
            reads[m], writes[m] = set(), set()
            for line in lines:
                for name in re.findall(r"\{(?:DATA_DIR|OUT_DIR)\}/(\w+)\.csv", line):
                    (writes if ".to_csv(" in line else reads)[m].add(name)
        producer = {csv: m for m, cs in writes.items() for csv in cs}

        def upstream(module):
            seen, stack = set(), [by_module[module].name]
            while stack:
                for d in BY_NAME[stack.pop()].deps:
                    if d not in seen:
                        seen.add(d)
                        stack.append(d)
            return seen

        for m in modules:
            for csv in reads[m]:
                assert csv in producer, f"{m} reads {csv}.csv, which no batch writes"
                assert by_module[producer[csv]].name in upstream(m), (
                    f"{m} reads {csv}.csv (written by {producer[csv]}) without depending on it")

    def test_generator_nodes_list_exactly_the_csvs_the_module_writes(self):
        for n in GENERATOR_NODES:
            module = n.argv[2].split(".", 1)[1]
            with open(os.path.join(REPO, "generators", f"{module}.py")) as f:
                written = {f"data/raw/{c}.csv" for c in
                           re.findall(r"\{(?:DATA_DIR|OUT_DIR)\}/(\w+)\.csv\"", "\n".join(
                               l for l in f.read().splitlines() if ".to_csv(" in l))}
            assert set(n.mutates) == written, n.name

    def test_every_raw_csv_has_a_producing_node(self):
        produced = {p for n in GENERATOR_NODES for p in n.mutates}
        on_disk = {f"data/raw/{os.path.basename(p)}"
                   for p in glob.glob(os.path.join(REPO, "data", "raw", "*.csv"))}
        assert on_disk <= produced, f"raw files with no generator node: {sorted(on_disk - produced)}"

    def test_every_test_file_belongs_to_exactly_one_qa_gate(self):
        tests = {os.path.relpath(p, REPO) for p in glob.glob(os.path.join(REPO, "tests", "test_*.py"))}
        pipeline_ = {os.path.relpath(p, REPO) for p in glob.glob(os.path.join(REPO, "tests", "test_pipeline_*.py"))}
        raw = {os.path.relpath(p, REPO) for p in glob.glob(os.path.join(REPO, "tests", "test_phase1_*.py"))}
        marts = tests - pipeline_ - raw
        assert pipeline_ and raw and marts
        assert pipeline_.isdisjoint(raw)
        # qa_marts' argv must be the complement of the other two globs
        argv = BY_NAME["qa_marts"].argv
        assert "--ignore-glob=tests/test_phase1_*.py" in argv
        assert "--ignore-glob=tests/test_pipeline_*.py" in argv


class TestDocumentation:
    def test_pipeline_readme_lists_every_contracted_artifact_and_its_sla(self):
        with open(os.path.join(REPO, "pipeline", "README.md")) as f:
            readme = f.read()
        for a in load_contract()["artifacts"]:
            row = next((l for l in readme.splitlines() if l.startswith(f"| `{a['name']}` |")), None)
            assert row is not None, f"pipeline/README.md has no table row for {a['name']}"
            assert row.rstrip().endswith(f"| {a['max_staleness_days']} |"), (
                f"pipeline/README.md SLA for {a['name']} differs from the contract")

    def test_readme_generator_table_matches_the_dag(self):
        with open(os.path.join(REPO, "README.md")) as f:
            readme = f.read()
        for n in GENERATOR_NODES:
            assert f"python3 -m {n.argv[2]}`" in readme, n.name

    def test_requirements_pin_every_third_party_root_import(self):
        with open(os.path.join(REPO, "requirements.txt")) as f:
            pinned = {l.split("==")[0].lower() for l in f if "==" in l and not l.startswith("#")}
        assert {"numpy", "pandas", "scipy", "scikit-learn", "duckdb", "pytest",
                "dbt-core", "dbt-duckdb"} <= pinned
        imported = set()
        for d in ("analytics", "generators", "pipeline"):
            for p in glob.glob(os.path.join(REPO, d, "*.py")):
                with open(p) as f:
                    imported |= set(re.findall(r"^(?:import|from) ([a-z_0-9]+)", f.read(), re.M))
        third_party = imported & {"numpy", "pandas", "scipy", "sklearn", "duckdb", "yaml",
                                  "statsmodels", "matplotlib", "anthropic", "pyarrow"}
        module_to_dist = {"sklearn": "scikit-learn"}
        for m in third_party:
            assert module_to_dist.get(m, m) in pinned, f"{m} is imported but not pinned in requirements.txt"
