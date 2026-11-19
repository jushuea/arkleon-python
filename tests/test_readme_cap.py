from pathlib import Path


README = Path(__file__).resolve().parent.parent / "README.md"


def test_readme_states_free_v1_cap():
    text = README.read_text(encoding="utf-8")
    assert "The free `/v1` tier allows 500 requests / day." in text


def test_readme_states_concept_alias():
    text = README.read_text(encoding="utf-8")
    assert "`concept_alias` is accepted on `facts()`: it takes a plain-language concept name, such as `revenue`, in place of a raw us-gaap `tag`, and it cannot be combined with `tag`." in text
    assert "available after /v1 ships it" not in text


def test_readme_no_stale_100_per_day():
    text = README.read_text(encoding="utf-8")
    assert "100 requests / day" not in text
