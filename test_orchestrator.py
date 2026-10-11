import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from orchestrator import run  # noqa: E402
from sample_data import make_sample  # noqa: E402


def test_quality_score_improves():
    out = run(make_sample())
    assert out["scores_after"]["overall"] > out["scores_before"]["overall"]


def test_no_duplicates_or_impossible_ages_remain():
    df = run(make_sample())["df"]
    assert not df.duplicated().any()
    assert df["age"].between(0, 120).all()


def test_unsafe_fixes_are_escalated_not_guessed():
    out = run(make_sample())
    cols = {i["column"] for i in out["issues"]}
    assert "email" in cols and "signup_date" in cols  # blanks left for a human


def test_clean_data_skips_fixer():
    clean = pd.DataFrame({"customer_id": [1, 2, 3], "country": ["India", "USA", "UK"]})
    out = run(clean)
    assert out["applied"] == [] and out["issues"] == []
