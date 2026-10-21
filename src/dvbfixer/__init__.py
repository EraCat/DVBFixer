"""dvbfixer — PDB structure preparation tools."""

__version__ = "0.9.1"

# Silence MDAnalysis's "Unknown element" chatter — Reduce and tleap
# occasionally emit atom lines with a blank element column (77-78);
# MDA warns on every such atom during PDB load. Not actionable at
# our level. dvbfixer already suppresses MDA DeprecationWarnings via
# `pyproject.toml`'s `filterwarnings`, but that only applies during
# pytest. Do it here so it also applies at CLI runtime.
import warnings as _warnings

_warnings.filterwarnings(
    "ignore",
    message=r".*Unknown element.*",
    category=UserWarning,
    module=r"MDAnalysis\..*",
)
_warnings.filterwarnings(
    "ignore",
    message=r".*Element information is missing.*",
    category=UserWarning,
    module=r"MDAnalysis\..*",
)
