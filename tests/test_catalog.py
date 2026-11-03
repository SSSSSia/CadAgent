"""The committed TS file is the Chinese catalog the panel reads."""
from __future__ import annotations

import os

from ui.catalog import build_ts, load_catalog, qm_path, ts_path
from ui.strings import _EN, _ZH


def test_committed_ts_matches_the_string_tables():
    path = ts_path()
    assert os.path.isfile(path)
    assert load_catalog(path) == load_catalog_from_text(build_ts(_EN, _ZH))
    catalog = load_catalog(path)
    for key, english in _EN.items():
        assert catalog[english] == _ZH[key]


def test_qm_path_sits_beside_the_ts_file():
    assert qm_path().endswith("cadagent_zh.qm")
    assert os.path.dirname(qm_path()) == os.path.dirname(ts_path())


def load_catalog_from_text(xml: str) -> dict[str, str]:
    import io
    import xml.etree.ElementTree as ET
    root = ET.parse(io.StringIO(xml)).getroot()
    return {
        message.findtext("source"): message.findtext("translation")
        for message in root.iter("message")
    }
