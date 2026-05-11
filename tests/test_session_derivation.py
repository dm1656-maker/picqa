"""Tests for the session-ID derivation logic in xml_parser._derive_session."""

from __future__ import annotations

from pathlib import Path

from picqa.io.xml_parser import _derive_session


def test_standard_session_folder_preserved():
    """Standard YYYYMMDD_HHMMSS folder name should pass through unchanged."""
    # In real HY202103 layout, XML files sit directly inside the session folder
    p = Path("/data/D07/20190715_190855/HY202103_D07_(0,0)_LION1_DCM_LMZC.xml")
    result = _derive_session(p, creation_date="Mon Jul 15 19:17:03 2019")
    # Standard folder name wins over CreationDate parsing
    assert result == "20190715_190855"


def test_creation_date_used_when_folder_nonstandard():
    """A flat / non-standard folder name should trigger CreationDate fallback."""
    p = Path("/some/flat/dir/file.xml")
    result = _derive_session(p, creation_date="Mon Jul 15 19:17:03 2019")
    assert result == "20190715_1917"


def test_minute_bucketing_groups_close_measurements():
    """Two measurements taken seconds apart end up in the same minute bucket."""
    p = Path("/flat/file.xml")
    s1 = _derive_session(p, "Mon Jul 15 19:17:03 2019")
    s2 = _derive_session(p, "Mon Jul 15 19:17:58 2019")
    assert s1 == s2 == "20190715_1917"


def test_minute_bucketing_separates_distant_measurements():
    """Measurements 5 minutes apart land in different sessions."""
    p = Path("/flat/file.xml")
    s1 = _derive_session(p, "Mon Jul 15 19:17:03 2019")
    s2 = _derive_session(p, "Mon Jul 15 19:23:09 2019")
    assert s1 != s2
    assert s1 == "20190715_1917"
    assert s2 == "20190715_1923"


def test_unparseable_creation_date_falls_back_to_folder():
    """If CreationDate is malformed, use parent folder name (original behaviour)."""
    p = Path("/flat/myfolder/file.xml")
    result = _derive_session(p, creation_date="garbage timestamp")
    assert result == "myfolder"


def test_missing_creation_date_falls_back_to_folder():
    """If CreationDate is empty, use parent folder name."""
    p = Path("/anywhere/parent/file.xml")
    result = _derive_session(p, creation_date="")
    assert result == "parent"


def test_arbitrary_folder_name_still_works_with_good_creation_date():
    """Nested arbitrary folders + good timestamp → minute-bucket session."""
    p = Path("/data/my_random/nested/deep/file.xml")
    result = _derive_session(p, "Mon Jan  6 14:25:42 2020")
    assert result == "20200106_1425"
