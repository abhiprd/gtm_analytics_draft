"""Freshness contract: evaluation against synthetic fresh / stale / missing
artifacts, basis-date arithmetic, contract validation, the CLI exit code,
and the committed contract against the committed outputs.

Synthetic cases build their evidence in a temp directory, so nothing here
touches real data; the committed-state test skips the dbt marts entry
(data/acme_gtm.duckdb does not exist until dbt_build has run).
"""
import csv
import json
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import cli, freshness  # noqa: E402
from pipeline.freshness import (  # noqa: E402
    FRESH, MISSING, STALE, ContractError, basis_date, evaluate, evaluate_artifact,
    exit_code, load_contract, validate_contract,
)

REF = date(2025, 12, 31)


def _artifact(**kw):
    a = {
        "name": "x", "kind": "analytics", "owner": "RevOps", "cadence": "weekly",
        "basis": "horizon", "max_staleness_days": 10, "depends_on": [],
        "evidence": [{"type": "perf_log", "model_name": "m"}],
        "fresh_means": "f", "sla_rationale": "r",
    }
    a.update(kw)
    return a


def _log(root, rows):
    os.makedirs(root / "data", exist_ok=True)
    with open(root / "data" / "model_performance_history.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model_name", "as_of_date", "metric_name", "metric_value"])
        w.writerows(rows)


# --------------------------------------------------------------------------
# basis dates
# --------------------------------------------------------------------------

class TestBasisDate:
    def test_horizon_is_the_reference_itself(self):
        assert basis_date("horizon", date(2025, 12, 31)) == date(2025, 12, 31)

    @pytest.mark.parametrize("ref,expected", [
        (date(2025, 12, 31), date(2025, 11, 30)),   # month-end: its own month is not complete
        (date(2026, 1, 15), date(2025, 12, 31)),
        (date(2026, 3, 1), date(2026, 2, 28)),
        (date(2024, 3, 1), date(2024, 2, 29)),      # leap year
        (date(2026, 1, 1), date(2025, 12, 31)),
    ])
    def test_last_complete_month(self, ref, expected):
        assert basis_date("last_complete_month", ref) == expected


# --------------------------------------------------------------------------
# evaluation: fresh / stale / missing
# --------------------------------------------------------------------------

class TestEvaluation:
    def test_fresh_when_evidence_is_within_sla(self, tmp_path):
        _log(tmp_path, [["m", "2025-12-25", "auc", 0.7]])
        r = evaluate_artifact(_artifact(), REF, str(tmp_path))
        assert r.state == FRESH and r.worst_staleness_days == 6

    def test_boundary_is_inclusive(self, tmp_path):
        _log(tmp_path, [["m", "2025-12-21", "auc", 0.7]])  # exactly 10 days
        assert evaluate_artifact(_artifact(), REF, str(tmp_path)).state == FRESH
        _log(tmp_path, [["m", "2025-12-20", "auc", 0.7]])  # 11 days
        assert evaluate_artifact(_artifact(), REF, str(tmp_path)).state == STALE

    def test_stale_when_evidence_is_older_than_sla(self, tmp_path):
        _log(tmp_path, [["m", "2025-06-30", "auc", 0.7], ["m", "2025-11-01", "auc", 0.7]])
        r = evaluate_artifact(_artifact(), REF, str(tmp_path))
        assert r.state == STALE and r.worst_staleness_days == 60

    def test_evidence_ahead_of_the_basis_is_fresh_not_negative(self, tmp_path):
        _log(tmp_path, [["m", "2025-12-31", "auc", 0.7]])
        r = evaluate_artifact(_artifact(basis="last_complete_month"), REF, str(tmp_path))
        assert r.state == FRESH and r.worst_staleness_days == 0

    def test_missing_when_the_artifact_has_no_rows(self, tmp_path):
        _log(tmp_path, [["other_model", "2025-12-31", "auc", 0.7]])
        r = evaluate_artifact(_artifact(), REF, str(tmp_path))
        assert r.state == MISSING and "no rows" in r.evidence[0].detail

    def test_missing_when_the_log_file_is_absent(self, tmp_path):
        assert evaluate_artifact(_artifact(), REF, str(tmp_path)).state == MISSING

    def test_worst_evidence_source_decides(self, tmp_path):
        _log(tmp_path, [["m", "2025-12-31", "auc", 0.7]])
        art = _artifact(evidence=[
            {"type": "perf_log", "model_name": "m"},
            {"type": "output_files", "glob": "analytics/outputs/x_*.json"}])
        assert evaluate_artifact(art, REF, str(tmp_path)).state == MISSING
        out = tmp_path / "analytics" / "outputs"
        out.mkdir(parents=True)
        (out / "x_2025-06-30.json").write_text("{}")
        assert evaluate_artifact(art, REF, str(tmp_path)).state == STALE
        (out / "x_2025-12-30.json").write_text("{}")
        assert evaluate_artifact(art, REF, str(tmp_path)).state == FRESH

    def test_empty_output_file_does_not_count_as_evidence(self, tmp_path):
        out = tmp_path / "analytics" / "outputs"
        out.mkdir(parents=True)
        (out / "x_2025-12-31.json").write_text("")
        art = _artifact(evidence=[{"type": "output_files", "glob": "analytics/outputs/x_*.json"}])
        assert evaluate_artifact(art, REF, str(tmp_path)).state == MISSING

    def test_csv_max_and_json_field_evidence(self, tmp_path):
        (tmp_path / "data").mkdir()
        with open(tmp_path / "data" / "t.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "d"])
            w.writerows([[1, "2025-10-01"], [2, "2025-12-30 00:00:00"]])
        (tmp_path / "status.json").write_text(json.dumps({"_meta": {"last_reviewed": "2025-09-29"}}))
        art = _artifact(max_staleness_days=99, cadence="quarterly", evidence=[
            {"type": "csv_max", "path": "data/t.csv", "column": "d"},
            {"type": "json_field", "path": "status.json", "field": "_meta.last_reviewed"}])
        r = evaluate_artifact(art, REF, str(tmp_path))
        assert [e.staleness_days for e in r.evidence] == [1, 93] and r.state == FRESH
        art["max_staleness_days"] = 90
        assert evaluate_artifact(art, REF, str(tmp_path)).state == STALE

    def test_missing_database_is_missing_not_stale(self, tmp_path):
        art = _artifact(cadence="monthly", max_staleness_days=35, evidence=[
            {"type": "duckdb_max", "table": "main_marts.mart_growth_bridge", "column": "month"}])
        r = evaluate_artifact(art, REF, str(tmp_path))
        assert r.state == MISSING and "dbt_build" in r.evidence[0].detail

    def test_registry_evidence_follows_the_gate(self, tmp_path):
        from pipeline.gate import Finding, GateReport
        bad = GateReport("registry", findings=[Finding("registry", "stale", "x")])
        art = _artifact(cadence="event_driven", max_staleness_days=0,
                        evidence=[{"type": "registry_current"}])
        assert evaluate_artifact(art, REF, str(tmp_path), registry_check=lambda: GateReport("registry")).state == FRESH
        assert evaluate_artifact(art, REF, str(tmp_path), registry_check=lambda: bad).state == STALE

    def test_exit_code_is_nonzero_on_any_violation(self, tmp_path):
        _log(tmp_path, [["m", "2025-12-31", "auc", 0.7]])
        contract = {"artifacts": [_artifact(name="ok"), _artifact(name="gone", evidence=[
            {"type": "perf_log", "model_name": "absent"}])]}
        results = evaluate(contract, REF, str(tmp_path))
        assert [r.state for r in results] == [FRESH, MISSING]
        assert exit_code(results) == 1
        assert exit_code(results[:1]) == 0


# --------------------------------------------------------------------------
# contract validation
# --------------------------------------------------------------------------

class TestContractValidation:
    def test_sla_tighter_than_cadence_is_rejected(self):
        with pytest.raises(ContractError, match="tighter than its monthly cadence"):
            validate_contract({"artifacts": [_artifact(cadence="monthly", max_staleness_days=7)]})

    @pytest.mark.parametrize("patch,match", [
        ({"basis": "whenever"}, "unknown basis"),
        ({"cadence": "hourly"}, "unknown cadence"),
        ({"kind": "widget"}, "unknown kind"),
        ({"evidence": []}, "no evidence"),
        ({"evidence": [{"type": "telepathy"}]}, "unknown evidence type"),
        ({"owner": " "}, "empty owner"),
        ({"depends_on": ["ghost"]}, "unknown artifact"),
    ])
    def test_malformed_entries_are_rejected(self, patch, match):
        with pytest.raises(ContractError, match=match):
            validate_contract({"artifacts": [_artifact(**patch)]})

    def test_duplicate_names_are_rejected(self):
        with pytest.raises(ContractError, match="duplicate"):
            validate_contract({"artifacts": [_artifact(), _artifact()]})

    def test_missing_required_field_is_rejected(self):
        a = _artifact()
        del a["sla_rationale"]
        with pytest.raises(ContractError, match="sla_rationale"):
            validate_contract({"artifacts": [a]})


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

class TestCli:
    def _contract_file(self, tmp_path, artifacts):
        p = tmp_path / "c.json"
        p.write_text(json.dumps({"artifacts": artifacts}))
        return str(p)

    def test_cli_returns_1_on_a_violation_and_0_when_clean(self, tmp_path, monkeypatch, capsys):
        _log(tmp_path, [["m", "2025-12-31", "auc", 0.7]])
        monkeypatch.setattr(freshness, "REPO_ROOT", str(tmp_path))
        contract = self._contract_file(tmp_path, [_artifact()])
        assert cli.main(["check-freshness", "--contract", contract, "--as-of", "2025-12-31"]) == 0
        # the same evidence, evaluated a year later, is stale
        assert cli.main(["check-freshness", "--contract", contract, "--as-of", "2026-12-31"]) == 1
        assert "STALE" in capsys.readouterr().out

    def test_bad_date_is_a_usage_error(self, capsys):
        assert cli.main(["check-freshness", "--as-of", "last tuesday"]) == 2
        assert "not an ISO date" in capsys.readouterr().err

    def test_json_output_is_machine_readable(self, tmp_path, monkeypatch, capsys):
        _log(tmp_path, [["m", "2025-12-31", "auc", 0.7]])
        monkeypatch.setattr(freshness, "REPO_ROOT", str(tmp_path))
        contract = self._contract_file(tmp_path, [_artifact()])
        assert cli.main(["check-freshness", "--contract", contract, "--json",
                         "--as-of", "2025-12-31"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True and payload["artifacts"][0]["state"] == "fresh"


# --------------------------------------------------------------------------
# the committed contract against the committed outputs
# --------------------------------------------------------------------------

class TestCommittedContract:
    def test_contract_is_well_formed_and_every_artifact_is_owned_and_reasoned(self):
        contract = load_contract()
        assert len(contract["artifacts"]) >= 26
        for a in contract["artifacts"]:
            assert a["owner"].strip() and len(a["sla_rationale"]) > 40, a["name"]

    def test_slas_are_not_uniform_boilerplate(self):
        slas = {a["max_staleness_days"] for a in load_contract()["artifacts"]}
        assert len(slas) >= 4

    def test_committed_artifacts_are_fresh_at_the_dataset_horizon(self):
        contract = load_contract()
        results = evaluate(contract, freshness.default_reference(),
                           only=[a["name"] for a in contract["artifacts"] if a["name"] != "dbt_marts"],
                           registry_check=lambda: __import__("pipeline.gate", fromlist=["x"]).check_registry())
        stale = [(r.name, r.state, r.worst_staleness_days, r.sla_days) for r in results if r.state != FRESH]
        assert not stale, stale

    def test_the_same_artifacts_go_stale_when_the_reference_moves_on(self):
        contract = load_contract()
        results = evaluate(contract, date(2026, 6, 30),
                           only=["weekly_readout", "playbook_triggers", "raw_data"])
        assert all(r.state == STALE for r in results)
