"""Governance gate: a broken identity check, a failed invariant or a stale
semantic registry makes `python3 -m pipeline gate` exit nonzero.

Everything here runs on hand-built results, temp copies and monkeypatches;
no real data or tracked file is edited. The end-to-end version against the
built marts is tests/test_governance_gate_marts.py.
"""
import copy
import json
import os
import shutil
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import cli, gate  # noqa: E402

REPO = gate.REPO_ROOT


def _clean_result():
    edge = {"edge_id": "growth_pillar_identity", "parent": "Growth pillar",
            "formula": "Starting + New logo + Expansion - Contraction - Churn",
            "result": {"passed": True, "max_abs_diff": 0.0}}
    frame = lambda ok: pd.DataFrame({"check": ["c1", "c2"], "passed": [True, ok]})  # noqa: E731
    return {
        "metric_tree_integrity": {"computed_edges": [edge], "edges_checked": 1,
                                  "edges_not_computable": 2, "edges_validated_elsewhere": 3},
        "marts_data_quality": {"referential_integrity": frame(True), "completeness": frame(True),
                               "distributional_sanity": frame(True), "volume_sufficiency": frame(True)},
        "invariant_governance": {"checks": {"no_segment_downgrade": {"passed": True},
                                            "currency_usd_only": {"passed": True}}},
        "synthetic_validation": {"all_pass": True, "n_scenarios": 5, "results": []},
        "summary": {"checks_passed": 10, "checks_total": 10},
    }


class TestJudgeGovernance:
    def test_clean_result_passes(self):
        assert gate.judge_governance(_clean_result()).passed

    def test_a_broken_metric_tree_identity_fails_and_is_named(self):
        r = _clean_result()
        r["metric_tree_integrity"]["computed_edges"][0]["result"] = {"passed": False, "max_abs_diff": 1250.5}
        report = gate.judge_governance(r)
        assert not report.passed
        assert report.findings[0].family == "metric_tree_identity"
        assert report.findings[0].name == "growth_pillar_identity"
        assert "1250.5" in report.findings[0].detail

    def test_a_failed_marts_check_fails_and_is_named(self):
        r = _clean_result()
        r["marts_data_quality"]["completeness"] = pd.DataFrame(
            {"check": ["dim_accounts.segment not null"], "passed": [False]})
        report = gate.judge_governance(r)
        assert [f.name for f in report.findings] == ["dim_accounts.segment not null"]

    def test_a_failed_invariant_fails(self):
        r = _clean_result()
        r["invariant_governance"]["checks"]["no_segment_downgrade"] = {"passed": False, "detail": "x"}
        assert [f.family for f in gate.judge_governance(r).findings] == ["invariant"]

    def test_a_governance_module_that_no_longer_catches_injected_violations_fails(self):
        r = _clean_result()
        r["synthetic_validation"] = {"all_pass": False, "n_scenarios": 1,
                                     "results": [{"scenario": "growth_identity_broken_fails",
                                                  "matches_expectation": False}]}
        assert gate.judge_governance(r).findings[0].family == "synthetic_self_check"


class TestGateExitCode:
    def _patch(self, monkeypatch, tmp_path, result):
        db = tmp_path / "x.duckdb"
        db.write_text("")
        monkeypatch.setattr(gate, "DB_PATH", str(db))
        monkeypatch.setattr(gate, "run_governance", lambda as_of: result)

    def test_exit_0_when_governance_is_clean(self, monkeypatch, tmp_path, capsys):
        self._patch(monkeypatch, tmp_path, _clean_result())
        assert cli.main(["gate", "--check", "identity"]) == 0
        assert "gate[identity]: PASS" in capsys.readouterr().out

    def test_exit_1_when_an_identity_check_is_broken(self, monkeypatch, tmp_path, capsys):
        broken = _clean_result()
        broken["metric_tree_integrity"]["computed_edges"][0]["result"]["passed"] = False
        self._patch(monkeypatch, tmp_path, broken)
        assert cli.main(["gate", "--check", "identity"]) == 1
        out = capsys.readouterr().out
        assert "FAIL [metric_tree_identity] growth_pillar_identity" in out

    def test_missing_database_fails_with_an_actionable_message(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(gate, "DB_PATH", str(tmp_path / "absent.duckdb"))
        assert cli.main(["gate", "--check", "identity"]) == 1
        assert "dbt_build" in capsys.readouterr().out


class TestRegistry:
    @pytest.fixture
    def tree_and_registry(self, tmp_path):
        tree = tmp_path / "tree.md"
        shutil.copy(gate.TREE_PATH, tree)
        reg = tmp_path / "registry.json"
        shutil.copy(gate.REGISTRY_PATH, reg)
        return tree, reg

    def test_committed_registry_is_current(self):
        report = gate.check_registry()
        assert report.passed, [f.detail for f in report.findings]

    def test_stamped_hash_match_is_fresh_without_reparsing(self, tree_and_registry):
        tree, reg = tree_and_registry
        report = gate.check_registry(tree_path=str(tree), registry_path=str(reg),
                                     build_path=str(tree.parent / "does_not_exist.py"))
        assert report.passed and not report.warnings

    def test_a_structural_tree_change_makes_the_registry_stale(self, tree_and_registry):
        tree, reg = tree_and_registry
        text = tree.read_text(encoding="utf-8")
        assert "Win rate" in text
        tree.write_text(text.replace("Win rate", "Close rate", 1), encoding="utf-8")
        report = gate.check_registry(tree_path=str(tree), registry_path=str(reg))
        assert not report.passed
        assert report.findings[0].name == "stale"
        assert "build_registry.py" in report.findings[0].detail

    def test_a_prose_only_tree_edit_passes_with_a_warning(self, tree_and_registry):
        tree, reg = tree_and_registry
        tree.write_text(tree.read_text(encoding="utf-8") + "\n\n<!-- trailing note -->\n", encoding="utf-8")
        report = gate.check_registry(tree_path=str(tree), registry_path=str(reg))
        assert report.passed and report.warnings and "identical registry content" in report.warnings[0]
        strict = gate.check_registry(strict_stamp=True, tree_path=str(tree), registry_path=str(reg))
        assert not strict.passed and strict.findings[0].name == "stamp_lag"

    def test_a_tree_that_no_longer_parses_is_stale(self, tree_and_registry):
        tree, reg = tree_and_registry
        tree.write_text("# not a metric tree\n", encoding="utf-8")
        report = gate.check_registry(tree_path=str(tree), registry_path=str(reg))
        assert not report.passed and report.findings[0].name == "tree_does_not_parse"

    def test_missing_registry_fails(self, tmp_path):
        report = gate.check_registry(registry_path=str(tmp_path / "nope.json"))
        assert not report.passed and report.findings[0].name == "missing"

    def test_cli_exit_code_follows_the_registry_verdict(self, monkeypatch, tree_and_registry):
        tree, reg = tree_and_registry
        monkeypatch.setattr(gate, "TREE_PATH", str(tree))
        monkeypatch.setattr(gate, "REGISTRY_PATH", str(reg))
        monkeypatch.setattr(
            gate, "check_registry",
            lambda strict_stamp=False, _orig=gate.check_registry: _orig(
                strict_stamp, str(tree), str(reg)))
        assert cli.main(["gate", "--check", "registry"]) == 0
        data = json.loads(reg.read_text())
        data["content_sha256"] = "0" * 64
        data["source_tree_sha256"] = "1" * 64
        reg.write_text(json.dumps(data))
        assert cli.main(["gate", "--check", "registry"]) == 1
