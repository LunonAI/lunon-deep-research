"""Unit tests for the DRB-leaderboard fetch helpers in p2_qianfan_fetch_articles.

The script's main() reaches out to a remote HF Space and is exercised by the
smoke-test step before each merge. These tests cover the two pure helpers
that decode the Space's response shape, so any drift in that contract
(header text, prompt-line format) fails loud locally.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# The script under test imports `gradio_client` at module top, which would
# raise ModuleNotFoundError during pytest collection on a lightweight CI
# image. importorskip turns that into a clean "skipped" status so missing
# the dependency is distinguishable from genuine test failures.
pytest.importorskip("gradio_client")

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "p2_qianfan_fetch_articles.py"
_spec = importlib.util.spec_from_file_location("p2_qianfan_fetch_articles", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def test_strip_article_wrapper_removes_header_and_lstrips():
    raw = "### Generated Article 📖\n\n# The Real Title\n\nBody."
    assert _mod._strip_article_wrapper(raw) == "# The Real Title\n\nBody."


def test_strip_article_wrapper_no_header_returns_lstripped_input():
    raw = "\n\n# Already clean\n\nBody."
    assert _mod._strip_article_wrapper(raw) == "# Already clean\n\nBody."


def test_strip_article_wrapper_only_removes_header_at_start():
    # An inline "Generated Article" mention later in the body must survive.
    raw = "### Generated Article 📖\n\n# Title\n\nNote: ### Generated Article 📖 was earlier on."
    out = _mod._strip_article_wrapper(raw)
    assert out.startswith("# Title")
    assert "### Generated Article 📖 was earlier on." in out


def test_extract_prompt_captures_full_description():
    user_md = (
        "### User Task 🎯\n\n"
        "**Task ID:** 91\n\n"
        "**Description:** Analyse the Saint Seiya franchise. Cover all armor classes."
    )
    assert _mod._extract_prompt(user_md) == ("Analyse the Saint Seiya franchise. Cover all armor classes.")


def test_extract_prompt_handles_multiline_description():
    user_md = "### User Task 🎯\n\n**Task ID:** 14\n\n**Description:** Line one.\n\nLine two.\nLine three."
    # DOTALL behaviour: capture from "Description:" to end of string.
    assert _mod._extract_prompt(user_md) == "Line one.\n\nLine two.\nLine three."


def test_extract_prompt_returns_empty_when_marker_missing():
    # The script's main() relies on this returning "" (falsy) so the
    # empty-prompt guard at the write site triggers. Documenting the
    # contract here means a refactor that returns None or a sentinel
    # string fails this test loudly rather than silently changing the
    # downstream write-path behaviour.
    assert _mod._extract_prompt("no description here") == ""


def test_task_disp_id_regex_matches_real_format():
    # Mirror the dropdown format the Space serves: "<id>. <prompt prefix>…".
    m = _mod._TASK_DISP_ID_RE.match("91. I would like a detailed analysis…")
    assert m is not None
    assert m.group(1) == "91"


def test_task_disp_id_regex_rejects_bare_int_and_dotless_strings():
    assert _mod._TASK_DISP_ID_RE.match("91") is None
    assert _mod._TASK_DISP_ID_RE.match("91-foo") is None
    # No space after the dot — also rejected.
    assert _mod._TASK_DISP_ID_RE.match("91.foo") is None
