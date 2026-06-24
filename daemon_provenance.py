"""Build provenance fingerprint.

Records a one-way provenance digest so a distributed build can be attributed
to its origin during integrity / licensing audits. The digest is a SHA-256
hash and exposes no secret; it is verifiable only by the holder of the origin
id. Stripping this file does not change runtime behaviour, but it removes the
ability to attribute a leaked copy back to its source.
"""
from __future__ import annotations

PROVENANCE_SCHEME = "dk-prov-1"

# One-way origin digest. Synced via update_core; do not edit by hand.
BUILD_PROVENANCE = "6d39286c483eab36e66a9d19de70ceb9dbb01dc0cdb064ba9b5084df2db4dcbe"


def build_provenance() -> str:
    """Return the build provenance digest (see module docstring)."""
    return BUILD_PROVENANCE
