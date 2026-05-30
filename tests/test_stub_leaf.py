"""P3b-v5 #2: stub-leaf telemetry. A terminal LEAF (H3+ heading with no deeper
child) is a STUB if its body is near-empty (<120 non-ws chars). The dev6 found
17-33% of Lunon's leaves were stubs vs Qianfan's full ~700-1000 CJK essays. The
length lever (#74) should drive this toward 0; this measures whether it did."""

from deep_research.pipeline import article_metrics as am


def test_leaf_stub_detection_excludes_containers():
    art = (
        "# T\n\n## 1 Chap\n\n### 1.1 Container\n\n"
        "#### 1.1.1 Full\n\n" + ("内容" * 100) + "\n\n"  # 200 CJK > floor → not stub
        "#### 1.1.2 Stub\n\nx\n"  # 1 char < floor → stub
    )
    m = am.compute(art)
    # 1.1 is a container (has H4 children) → not a leaf; the two H4s are leaves
    assert m["n_leaves"] == 2
    assert m["stub_leaf_frac"] == 0.5


def test_no_leaves_is_zero_not_error():
    m = am.compute("# T\n\n## 1 Chap\n\njust a chapter body, no sub-leaves.\n")
    assert m["n_leaves"] == 0 and m["stub_leaf_frac"] == 0.0
