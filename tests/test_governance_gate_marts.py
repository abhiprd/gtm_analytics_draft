"""End-to-end governance gate against the built marts: a deliberately
corrupted growth bridge (injected by monkeypatching the loader, never by
editing data) makes the real metric-tree identity check fail and the gate
exit nonzero. Needs data/acme_gtm.duckdb (runs after dbt_build).
"""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import cli, gate  # noqa: E402

DB = os.path.join(gate.REPO_ROOT, "data", "acme_gtm.duckdb")
pytestmark = pytest.mark.skipif(not os.path.exists(DB), reason="dbt_build has not run")

AS_OF = date(2025, 12, 31)


def test_gate_passes_on_the_built_marts():
    report = gate.check_identity(AS_OF)
    assert report.passed, [(f.family, f.name, f.detail) for f in report.findings]
    assert any("governance checks pass" in i for i in report.info)


def test_a_corrupted_growth_bridge_fails_the_real_identity_check(monkeypatch, capsys):
    from analytics import data_quality_governance as dqg
    real = dqg.load_growth_bridge

    def corrupted(as_of_date, con=None):
        df = real(as_of_date, con=con)
        df["ending_mrr"] = df["ending_mrr"] + 5_000.0  # breaks Starting + New + ... = Ending
        return df

    monkeypatch.setattr(dqg, "load_growth_bridge", corrupted)
    report = gate.check_identity(AS_OF)
    assert not report.passed
    assert "growth_pillar_identity" in [f.name for f in report.findings]

    assert cli.main(["gate", "--check", "identity", "--as-of", AS_OF.isoformat()]) == 1
    assert "FAIL [metric_tree_identity] growth_pillar_identity" in capsys.readouterr().out
