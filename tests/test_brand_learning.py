"""User brand alias / training layer unit tests."""

from services.brand_catalog import BrandCatalog
from services.brand_learning import apply_user_aliases, resolve_brand_with_user_learning


def test_apply_user_aliases_exact():
    aliases = [{"alias": "丸未", "canonical": "丸味"}]
    assert apply_user_aliases("丸未", aliases) == "丸味"
    assert apply_user_aliases("other", aliases) is None


def test_resolve_prefers_user_alias(tmp_path):
    path = tmp_path / "brands.json"
    path.write_text(
        '[{"canonical": "Acana", "aliases": ["爱肯拿"]}]',
        encoding="utf-8",
    )
    cat = BrandCatalog(data_path=str(path), score_cutoff=80)
    aliases = [{"alias": "丸未", "canonical": "丸味"}]
    assert (
        resolve_brand_with_user_learning(cat, "丸未", "我买了丸未冻干", aliases)
        == "丸味"
    )
    assert (
        resolve_brand_with_user_learning(cat, "爱肯拿", "爱肯拿鸡肉", aliases) == "Acana"
    )
