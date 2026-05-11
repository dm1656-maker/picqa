"""XML parser for photonic test measurement files.

Files share a common ``OIOMeasurement`` root and embed measurement data inside
``OpticalMeasurements`` or ``ElectroOpticalMeasurements`` subtrees. Different
test types (``DCM_LMZO``, ``DCM_GPDO``, ``OTEST_L3OTE``...) put data in
slightly different containers, so this module handles them uniformly.
"""

from __future__ import annotations

import logging
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from picqa.io.bands import band_for_measurement, default_wavelength_for_band
from picqa.io.schemas import IVMeasurement, Measurement, WavelengthSweep

logger = logging.getLogger(__name__)

# Top-level wrapper tags whose first non-alignment Modulator/Loss block we want
_WRAPPER_TAGS = {"Modulator", "WaveguideLossMeasurement", "DetectorMeasurement"}


def _localname(tag: str) -> str:
    """Strip XML namespace if present."""
    return tag.split("}", 1)[-1]


def _to_array(text: str | None) -> np.ndarray:
    """Parse a comma-separated number string into a numpy array."""
    if text is None:
        return np.array([], dtype=float)
    return np.fromstring(text.strip(), sep=",")


def _parse_iv(elem: ET.Element) -> IVMeasurement | None:
    iv = elem.find(".//IVMeasurement")
    if iv is None:
        return None
    v_el = iv.find("Voltage")
    i_el = iv.find("Current")
    if v_el is None or i_el is None:
        return None
    v = _to_array(v_el.text)
    i = _to_array(i_el.text)
    if v.size == 0 or i.size == 0 or v.size != i.size:
        return None
    return IVMeasurement(voltage=v, current=i)


def _parse_sweeps(elem: ET.Element) -> list[WavelengthSweep]:
    sweeps: list[WavelengthSweep] = []
    for ws in elem.findall(".//WavelengthSweep"):
        l_el = ws.find("L")
        il_el = ws.find("IL")
        if l_el is None or il_el is None:
            continue
        L = _to_array(l_el.text)
        IL = _to_array(il_el.text)
        if L.size == 0 or IL.size == 0 or L.size != IL.size:
            continue
        try:
            bias = float(ws.attrib.get("DCBias", "nan"))
        except ValueError:
            bias = float("nan")
        try:
            power = float(ws.attrib.get("Power", "nan"))
        except ValueError:
            power = None
        sweeps.append(
            WavelengthSweep(
                wavelength_nm=L,
                insertion_loss_db=IL,
                dc_bias_v=bias,
                power_dbm=power if power is not None and not np.isnan(power) else None,
            )
        )
    return sweeps


def _find_main_block(root: ET.Element) -> ET.Element | None:
    """Return the first measurement block that is not an alignment reference."""
    candidates: list[ET.Element] = []
    for elem in root.iter():
        if _localname(elem.tag) in _WRAPPER_TAGS:
            candidates.append(elem)
    if not candidates:
        return None
    # Prefer a non-alignment block
    for c in candidates:
        name = c.attrib.get("Name", "")
        if "ALIGN" not in name.upper():
            return c
    return candidates[0]


def _parse_design_params(elem: ET.Element) -> dict[str, str]:
    params: dict[str, str] = {}
    for dp in elem.iter():
        if _localname(dp.tag) == "DesignParameter":
            symbol = dp.attrib.get("Symbol", "")
            if symbol and dp.text:
                params[symbol] = dp.text.strip()
    return params


# Regex for extracting test site tag from filename, e.g. ``..._LION1_DCM_LMZO.xml``
_TESTSITE_RE = re.compile(r"_LION1_(.+?)\.xml$")


def parse_measurement(path: str | os.PathLike) -> Measurement | None:
    """Parse a single XML file into a :class:`Measurement`.

    Returns ``None`` on parse failure. Logs the cause at WARNING level.
    """
    p = Path(path)
    if not p.is_file():
        logger.warning("File not found: %s", p)
        return None
    try:
        tree = ET.parse(p)
    except ET.ParseError as exc:
        logger.warning("XML parse error in %s: %s", p, exc)
        return None

    root = tree.getroot()
    ts = root.find("TestSiteInfo")
    info = dict(ts.attrib) if ts is not None else {}

    # Test site: take from XML if present, else from filename
    test_site = info.get("TestSite", "")
    if not test_site:
        m = _TESTSITE_RE.search(p.name)
        if m:
            test_site = m.group(1)

    main = _find_main_block(root)
    device_name = main.attrib.get("Name", "") if main is not None else ""

    # Parse IV and sweeps only from inside the main measurement block so we
    # don't pick up alignment-only WavelengthSweeps that some test sites
    # include in a separate ``ALIGN`` ``Modulator`` element.
    parse_root = main if main is not None else root
    iv = _parse_iv(parse_root)
    sweeps = _parse_sweeps(parse_root)
    design_params = _parse_design_params(main) if main is not None else {}

    align = root.find(".//AlignWavelength")
    align_wl: float | None = None
    if align is not None and align.text:
        try:
            align_wl = float(align.text.strip())
        except ValueError:
            align_wl = None

    # Design wavelength: prefer the XML's WL design parameter, fall back to
    # the band convention encoded in the test-site / device name.
    design_wl: float | None = None
    if "WL" in design_params:
        try:
            design_wl = float(design_params["WL"])
        except (TypeError, ValueError):
            design_wl = None

    band = band_for_measurement(
        design_wavelength_nm=design_wl,
        test_site=test_site,
        device_name=device_name,
    )
    if design_wl is None and band:
        design_wl = default_wavelength_for_band(band)

    try:
        die_col = int(info.get("DieColumn", 0))
        die_row = int(info.get("DieRow", 0))
    except ValueError:
        logger.warning("Invalid die coordinate in %s", p)
        return None

    creation_date = root.attrib.get("CreationDate", "")
    session = _derive_session(p, creation_date)

    return Measurement(
        wafer=info.get("Wafer", ""),
        die_col=die_col,
        die_row=die_row,
        batch=info.get("Batch", ""),
        maskset=info.get("Maskset", ""),
        test_site=test_site,
        device_name=device_name,
        design_params=design_params,
        design_wavelength_nm=design_wl,
        band=band,
        iv=iv,
        sweeps=sweeps,
        align_wavelength_nm=align_wl,
        creation_date=creation_date,
        session=session,
        source_path=str(p),
    )


# Standard session folder name pattern: YYYYMMDD_HHMMSS (HY202103 convention)
_SESSION_DIR_RE = re.compile(r"^\d{8}_\d{6}$")


def _derive_session(xml_path: Path, creation_date: str) -> str:
    """Derive a session ID for a measurement.

    Strategy (in priority order):

    1. If the XML file lives in a folder named like ``YYYYMMDD_HHMMSS``
       (the HY202103 convention), use that folder name. This preserves
       backward compatibility with the standard directory layout.

    2. Otherwise, parse the XML's ``CreationDate`` attribute (format
       ``"Mon Jul 15 19:17:03 2019"``) and bucket it into 1-minute
       windows so that dies measured close together in time are grouped
       into the same session. Returns a string like ``"20190715_1917"``.

    3. If neither is available, fall back to the parent folder name
       (which is what the parser did originally).
    """
    parent_name = xml_path.parent.name
    if _SESSION_DIR_RE.match(parent_name):
        return parent_name

    if creation_date:
        try:
            from datetime import datetime
            dt = datetime.strptime(creation_date, "%a %b %d %H:%M:%S %Y")
            return dt.strftime("%Y%m%d_%H%M")
        except ValueError:
            pass

    return parent_name


def parse_directory(
    data_dir: str | os.PathLike,
    test_site: str | list[str] | None = None,
) -> list[Measurement]:
    """Parse every XML under ``data_dir``, optionally filtering by test site.

    Parameters
    ----------
    data_dir : str | Path
        Root directory containing wafer subfolders (e.g. ``D08``, ``D24``).
    test_site : str | list[str] | None
        If a single string, only files whose test site matches are included.
        If a list, any of the listed test sites is accepted (useful for
        scanning multiple bands in one pass, e.g. ``["DCM_LMZO", "DCM_LMZC"]``).
        ``None`` parses every XML under the tree.
    """
    root_path = Path(data_dir)
    if not root_path.is_dir():
        raise FileNotFoundError(f"Data directory not found: {root_path}")

    if isinstance(test_site, str):
        wanted: set[str] | None = {test_site}
    elif test_site:
        wanted = set(test_site)
    else:
        wanted = None

    measurements: list[Measurement] = []
    for f in sorted(root_path.rglob("*.xml")):
        # Cheap pre-filter on filename to avoid parsing files we'll discard
        if wanted is not None:
            m_tag = _TESTSITE_RE.search(f.name)
            if m_tag and m_tag.group(1) not in wanted:
                continue
        m = parse_measurement(f)
        if m is None:
            continue
        if wanted is not None and m.test_site not in wanted:
            continue
        measurements.append(m)

    logger.info(
        "Parsed %d measurements from %s (test_site=%s)",
        len(measurements),
        root_path,
        test_site,
    )
    return measurements


def inventory(data_dir: str | os.PathLike) -> dict:
    """Return a quick inventory of files under ``data_dir`` (no full parse)."""
    root_path = Path(data_dir)
    if not root_path.is_dir():
        raise FileNotFoundError(f"Data directory not found: {root_path}")

    by_wafer: dict[str, int] = {}
    by_test: dict[str, int] = {}
    total_size = 0
    n_files = 0

    for f in root_path.rglob("*.xml"):
        n_files += 1
        total_size += f.stat().st_size
        # wafer = top-level folder under data_dir
        try:
            wafer = f.relative_to(root_path).parts[0]
            by_wafer[wafer] = by_wafer.get(wafer, 0) + 1
        except IndexError:
            pass
        m = _TESTSITE_RE.search(f.name)
        if m:
            by_test[m.group(1)] = by_test.get(m.group(1), 0) + 1

    return {
        "n_files": n_files,
        "total_size_bytes": total_size,
        "by_wafer": dict(sorted(by_wafer.items())),
        "by_test_site": dict(sorted(by_test.items(), key=lambda x: -x[1])),
    }
