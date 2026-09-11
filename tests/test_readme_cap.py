from pathlib import Path


README = Path(__file__).resolve().parent.parent / "README.md"


def test_readme_states_free_v1_cap():
    text = README.read_text(encoding="utf-8")
    assert "The free `/v1` tier allows 500 requests / day." in text


def test_readme_reserves_concept_alias():
    text = README.read_text(encoding="utf-8")
    assert "concept_alias" in text and "available after /v1 ships it" in text


def test_readme_no_stale_100_per_day():
    text = README.read_text(encoding="utf-8")
    assert "100 requests / day" not in text
