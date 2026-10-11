"""Chinese and English (DECISIONS D-046): every text the app shows has a Chinese version that
keeps its placeholders and markup, and no Chinese text makes a claim PRD §7 rule 5 forbids."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from i18n_keys import interface_keys, server_keys, zh_catalog  # noqa: E402

from app.i18n import language, tr, tr_message  # noqa: E402
from app.locales.zh import ZH as SERVER_ZH  # noqa: E402
from app.services import views  # noqa: E402

PLACEHOLDER = re.compile(r"\{(\w+?)(?:_\d+)?\}")
TAG = re.compile(r"</?\w+>")
# Messages only a developer sees (wrong environment settings); they stay in English.
TECHNICAL = {
    "unknown RPROV_TSA={value}", "unknown RPROV_BTC={value}", "unknown keystore {kind}",
    "not a SHA-256 hex digest", "unknown time-stamping authority {name}",
}


def _same_marks(key: str, value: str) -> bool:
    return (set(PLACEHOLDER.findall(key)) == set(PLACEHOLDER.findall(value))
            and sorted(TAG.findall(key)) == sorted(TAG.findall(value)))


def test_every_interface_text_has_a_chinese_version():
    keys, zh = interface_keys(), zh_catalog()
    assert len(keys) > 300
    assert [k for k in keys if k not in zh] == []
    assert [k for k in zh if k not in keys] == [], "unused entries in web/src/locales/zh.ts"
    assert [k for k, v in zh.items() if not _same_marks(k, v)] == []


def test_every_server_text_has_a_chinese_version():
    keys = server_keys()
    indirect = [*views.NODE_TYPE_LABELS.values(), *views.REL_LABELS.values(), views.TSA_LABEL, views.BTC_LABEL,
                views.CODE_NOT_SAVED, "Other", "other relation", "year", "month", "day"]
    missing = [k for k in [*keys, *indirect] if k not in SERVER_ZH and k not in TECHNICAL]
    assert missing == []
    assert [k for k, v in SERVER_ZH.items() if not _same_marks(k, v)] == []


@pytest.mark.parametrize("catalog", ["interface", "server"])
def test_no_forbidden_claims_in_chinese(catalog):
    from tests.unit.test_forbidden_claims import _hits

    values = zh_catalog().values() if catalog == "interface" else SERVER_ZH.values()
    assert [v for v in values if _hits(v)] == []


def test_server_texts_follow_the_request_language():
    assert tr("Verified record") == "Verified record"
    with language("zh-CN"):
        assert tr("Verified record") == "可验证记录"
        assert tr("{label}: pending", label=tr("Bitcoin anchor")) == "比特币时间锚定：等待中"
        # Errors are written in English where raised and translated on the way out, values kept.
        assert tr_message("the backup password needs at least 8 characters") == "备份密码至少需要 8 个字符"
        assert tr_message("unknown relation cites; use one of revises, uses") == \
            "未知的关系 cites；请用其中之一：revises, uses"
        assert tr_message("something nobody translated") == "something nobody translated"
    assert tr("Verified record") == "Verified record"
