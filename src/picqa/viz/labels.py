"""Plot labels (Korean / English).

Lookup is dict-based with a global default language. Falls back to English
if the requested key isn't translated.
"""

from __future__ import annotations

import os

# Default language can be overridden by env var or set_language()
_LANG = os.environ.get("PICQA_LANG", "ko").lower()


def set_language(lang: str) -> None:
    """Set the default plot label language ('ko' or 'en')."""
    global _LANG
    _LANG = lang.lower()


def get_language() -> str:
    return _LANG


# Label dictionary: key → {lang: text}
_LABELS: dict[str, dict[str, str]] = {
    # Axis labels
    "voltage": {"ko": "전압 (V)", "en": "Voltage (V)"},
    "current_abs": {"ko": "|전류| (A)", "en": "|Current| (A)"},
    "current": {"ko": "전류 (A)", "en": "Current (A)"},
    "wavelength": {"ko": "파장 (nm)", "en": "Wavelength (nm)"},
    "wavelength_shift_pm": {"ko": "파장 이동량  Δλ  (pm)",
                            "en": "Wavelength shift  Δλ  (pm)"},
    "il_db": {"ko": "삽입 손실 IL (dB)", "en": "IL (dB)"},
    "tracked_notch_nm": {"ko": "추적된 notch 파장 (nm)",
                         "en": "Tracked notch wavelength (nm)"},
    "phase_shift_over_pi": {"ko": "위상 변화 Δφ / π",
                            "en": "Phase shift  Δφ / π"},
    "phase_shift": {"ko": "위상 변화", "en": "Phase shift"},
    "vpi_l_vcm": {"ko": "Vπ·L  (V·cm)", "en": "VpiL (V·cm)"},
    "die_col": {"ko": "Die 가로 (Column)", "en": "Die Column"},
    "die_row": {"ko": "Die 세로 (Row)", "en": "Die Row"},
    "die_radius": {"ko": "Die 반경 (die 단위)",
                   "en": "Die radius (units of die spacing)"},
    "length_um": {"ko": "Phase shifter 길이 (µm)", "en": "Length (µm)"},
    "il_drop_vs_ref": {"ko": "REF 대비 IL 강하 (dB)",
                       "en": "IL drop vs REF (dB)"},
    "dil_dv": {"ko": "변조 효율 dIL/dV (dB/V)",
               "en": "Modulation efficiency dIL/dV (dB/V)"},

    # Titles and headers
    "iv_title": {"ko": "IV 특성 곡선", "en": "IV characteristics"},
    "spectra_at_bias": {"ko": "전송 스펙트럼 @ DC bias = {bias:+.1f} V",
                        "en": "Transmission spectra @ DC bias = {bias:+.1f} V"},
    "bias_dependent": {"ko": "전압별 스펙트럼 변화: {wafer}/{die}{band}",
                       "en": "Bias-dependent spectra: {wafer}/{die}{band}"},
    "zoom_at_design": {"ko": "{design:.0f} nm 부근 줌인",
                       "en": "Zoom near design wavelength ({design:.0f} nm)"},
    "vlambda_title": {"ko": "V-λ 분석: {wafer}/{die}{band}",
                      "en": "V-λ characterisation: {wafer}/{die}{band}"},
    "vphi_title": {"ko": "V-φ 분석: {wafer}/{die}{band}",
                   "en": "V-phi characterisation: {wafer}/{die}{band}"},
    "vphi_relation": {"ko": "V-φ 관계  (Vπ = {vpi:.2f} V)",
                      "en": "V-φ relation  (Vπ = {vpi:.2f} V)"},
    "notch_shift_vs_bias": {"ko": "Notch 시프트 vs 전압",
                            "en": "Notch shift vs bias"},
    "vpi_per_wafer": {"ko": "웨이퍼별 Vπ (정상 die)",
                      "en": "Vπ per wafer (working dies)"},
    "vpi_distribution_title": {"ko": "웨이퍼 간 Vπ 분포",
                               "en": "Vπ distribution across wafers"},
    "vpi_l_fom": {"ko": "Vπ·L 성능 지표", "en": "Vπ·L figure of merit"},
    "wafer_map_title": {"ko": "웨이퍼 맵: {metric}",
                        "en": "Wafer map: {metric}"},
    "efficiency_score_title": {"ko": "Die별 종합 효율 점수",
                               "en": "Per-die efficiency score"},
    "sweet_spot_title": {"ko": "Sweet Spot 맵: 일관되게 상위에 들어가는 위치",
                         "en": "Sweet-spot map: positions consistently in the top tier"},
    "n_wafers_top": {"ko": "상위 25% 진입 웨이퍼 수",
                     "en": "# of wafers where this position is in the top tier"},
    "mean_eff_across": {"ko": "전체 웨이퍼 평균 효율 점수",
                        "en": "Mean efficiency score across all wafers"},
    "vs_radius": {"ko": "{metric} vs 웨이퍼 반경",
                  "en": "{metric} vs wafer radius"},
    "center_vs_edge": {"ko": "중심부 vs 외각부 비교",
                       "en": "Center vs edge comparison"},
    "grating_il_radius": {"ko": "그레이팅 커플러 IL의 반경 의존성",
                          "en": "Grating coupler IL vs wafer radius"},

    # PN modulator
    "pn_il_drop_title": {"ko": "PN 변조기 — REF 대비 IL 강하",
                         "en": "PN modulator — IL drop vs REF"},
    "pn_modulation_title": {"ko": "PN 변조기 — 전기흡수 효율",
                            "en": "PN modulator — electroabsorption efficiency"},
    "pn_loss_vs_mod": {"ko": "도핑 손실 vs 변조 효율 trade-off",
                       "en": "Doping loss vs modulation efficiency"},
    "loss_per_um": {"ko": "단위 길이당 손실 (dB/cm)",
                    "en": "Loss per length (dB/cm)"},
    "mod_per_um": {"ko": "단위 길이당 변조 효율 (dB/V/mm)",
                   "en": "Modulation per length (dB/V/mm)"},

    # Annotations
    "linear_fit": {"ko": "선형 fit", "en": "Linear fit"},
    "median": {"ko": "중앙값", "en": "median"},
    "range_5_95": {"ko": "5–95 % 범위", "en": "5–95% range"},
    "modulation_eff": {"ko": "변조 효율", "en": "Modulation efficiency"},
    "fit_polynomial": {"ko": "기준 다항식 (O{order})",
                       "en": "Fit ref polynomial O{order}"},
    "transmission_measured": {"ko": "측정된 스펙트럼",
                              "en": "Transmission spectra - as measured"},
    "analysis_normalised": {"ko": "정규화된 스펙트럼",
                            "en": "Analysis spectra (normalised)"},
    "focus_left_peak": {"ko": "가장 왼쪽 notch 줌인",
                        "en": "Focus on spectral fit left peak"},
    "iv_analysis": {"ko": "IV 분석", "en": "IV-analysis"},
    "phase_analysis": {"ko": "위상 분석", "en": "Phase-analysis"},
    "vpil_analysis": {"ko": "Vπ·L 분석", "en": "VpiL-analysis"},
    "peak_left": {"ko": "왼쪽 notch fit", "en": "Peak fitO2 left"},
    "peak_center": {"ko": "가운데 notch fit", "en": "Peak fitO2 center"},
    "peak_right": {"ko": "오른쪽 notch fit", "en": "Peak fitO2 right"},
    "measured": {"ko": "측정값", "en": "Measured"},
    "n_dies": {"ko": "{n}개 die", "en": "n={n} dies"},
}


def L(key: str, lang: str | None = None, **kwargs) -> str:
    """Look up a label by key, in current or specified language.

    Examples
    --------
    >>> L("voltage")           # → "전압 (V)" or "Voltage (V)"
    >>> L("vpi_l_fom", lang="en")  # force English
    >>> L("spectra_at_bias", bias=-2.0)  # → "전송 스펙트럼 @ DC bias = -2.0 V"
    """
    use_lang = (lang or _LANG).lower()
    entry = _LABELS.get(key)
    if entry is None:
        # Unknown key — return the key itself, useful for debugging
        return key
    text = entry.get(use_lang) or entry.get("en") or list(entry.values())[0]
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


def configure_korean_font() -> str | None:
    """Configure matplotlib to use a Korean-capable font, if available.

    Returns the font name selected, or None if no suitable font found.
    """
    import matplotlib
    import matplotlib.font_manager as fm

    # Preferred fonts in order
    candidates = [
        "Malgun Gothic",          # Windows default
        "AppleGothic",            # macOS
        "Noto Sans CJK KR",       # Linux Noto (Korean variant)
        "NanumGothic",            # Common on Linux
        "Noto Sans KR",
        "Source Han Sans KR",
        # Fallbacks - the CJK font family ships as a single .ttc with
        # multiple language variants. matplotlib often only registers
        # the JP variant, but its Korean glyphs render correctly.
        "Noto Sans CJK JP",
        "Noto Sans CJK SC",
        "Noto Sans CJK TC",
    ]
    available = {f.name for f in fm.fontManager.ttflist}
    for name in candidates:
        if name in available:
            matplotlib.rcParams["font.family"] = name
            matplotlib.rcParams["axes.unicode_minus"] = False
            return name
    return None


# Try to set Korean font at import time so existing code "just works"
configure_korean_font()
