"""Device-specific feature extraction.

Each submodule converts :class:`~picqa.io.schemas.Measurement` objects into a
flat ``pandas.DataFrame`` of physical parameters.
"""

from picqa.extract.mzm import extract_mzm_features
from picqa.extract.photodetector import extract_pd_features
from picqa.extract.waveguide import extract_waveguide_loss

__all__ = [
    "extract_mzm_features",
    "extract_pd_features",
    "extract_waveguide_loss",
]
