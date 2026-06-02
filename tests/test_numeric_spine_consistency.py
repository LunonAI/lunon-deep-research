"""Round 8 (id-44): `_validate_numeric_spine_consistency` — fire when ≥2 figures
EACH self-declare THE headline total (主脊/头条) yet disagree by >3× or across
count-units.

The dev6/round-7b id-44 collapse (0.476 / 0.5365) was 3+ headline-declared totals
in conflict (120万 vs 4.5万 vs 40万 条/年, ~28× spread) — judge "体系崩塌" — which
dragged Readability/Insight/Comprehensiveness even though we BEAT the reference on
every other criterion. Fix C's soft "restate VERBATIM" prompt could not enforce it.

The discriminator is HEADLINE SELF-DECLARATION, not raw magnitude divergence: a
correct triangulation (Qianfan-style) tags its divergent figures as scope/scenario
COMPONENTS (中枢/区间/情景/外推) with only ONE declared headline, so the gate stays
silent. That is the property the earlier flag-any-two gate lacked.
"""

from deep_research.pipeline import validation

_NS = {"quantity": "年度碳滑板用量", "unit": "条", "owner_section": "S4", "methods": ["bottom-up", "top-down"]}


def test_skips_qualitative_plan_no_numeric_spine():
    # archetype gate: qualitative plans carry no numeric_spine -> silent (None).
    assert validation._validate_numeric_spine_consistency("数字主脊约 5 万条，主脊约 50 万条", None) is None
    assert validation._validate_numeric_spine_consistency("x", {}) is None


def test_skips_non_cjk_article():
    # the 万/亿 cue lexicon is Chinese-specific; an EN article is out of scope.
    en = "The headline spine figure is 50000 strips/year in one chapter and 500000 strips/year elsewhere."
    assert validation._validate_numeric_spine_consistency(en, _NS) is None


def test_fires_on_multiple_self_declared_headline_figures_in_conflict():
    # THE id-44 catch: three figures each declared THE headline at conflicting values.
    art = (
        "本章建立全文的数字主脊：地铁受电弓碳滑板年度更换用量约 120 万条/年，区间 90 万至 150 万条/年。\n"
        "两法收敛后给出报告唯一的头条数字：约 4.5 万条/年，构成整份报告的数字基准。\n"
        "第四章已锚定的头条实物用量约 40 万条/年，与单条均价联立给出市场规模。\n"
    )
    a = validation._validate_numeric_spine_consistency(art, _NS)
    assert a is not None and a["conflict"] is True
    assert a["spread_ratio"] >= 3.0
    # the conflicting totals are surfaced for the corrective instruction
    vals = a["headline_values"]
    assert any("4.50万" == v for v in vals) and any("120.00万" == v for v in vals)


def test_silent_on_single_headline_with_scope_tagged_components():
    # Qianfan-shape: ONE headline (主脊/头条) + scenario/method/forecast COMPONENTS
    # that do NOT carry the strong cue -> headline set collapses, no conflict.
    art = (
        "本报告的数字主脊为地铁受电弓碳滑板年度用量约 8 万根/年，区间 6 至 10 万根/年。\n"
        "全文各章一律复用 8 万根/年这一头条数字。\n"
        "保守情景下约 4 万根/年，乐观情景下约 11 万根/年（均为情景区间端点）。\n"
        "其中稳态主用受电弓年用量约 4.4 万根为分项小计；自上而下金额反推得 5 至 8 万根用于交叉验证；\n"
        "2030 年前瞻含脉冲约 13 万根（年份外推）。\n"
    )
    a = validation._validate_numeric_spine_consistency(art, _NS)
    assert a is not None and a["conflict"] is False


def test_fires_on_mixed_count_units_even_within_ratio():
    # 口径/unit-switch failure: same magnitude but 条 vs 片 is itself a conflict.
    art = "数字主脊约 5 万条/年。\n全文头条数字约 5 万片/年。\n"
    a = validation._validate_numeric_spine_consistency(art, _NS)
    assert a is not None and a["conflict"] is True and len(a["units"]) > 1


def test_per_unit_coefficients_do_not_count_as_headline_totals():
    # 每弓2条 sits near a 主脊 cue but is a coefficient, not an annual total —
    # the magnitude floor must keep it out so it can't inflate the spread.
    art = "数字主脊采用每弓 2 条的成对更换换算，年度用量约 5 万条/年。\n全文复用约 5 万条/年。"
    a = validation._validate_numeric_spine_consistency(art, _NS)
    assert a is not None and a["conflict"] is False
