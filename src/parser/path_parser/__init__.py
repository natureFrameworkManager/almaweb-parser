"""Package wrapper around the Studiengang-Extraktor.

Re-exports the public API so the rest of the parser can use

    from parser.path_parser import extract_for_paths, Studiengang

`studiengang_extractor` itself remains a standalone script (stdlib only) and
can still be run as ``python -m src.parser.path_parser.studiengang_extractor``.
"""

from .studiengang_extractor import (
    DEGREE_SPECIFICITY,
    FUZZY_THRESHOLD,
    Studiengang,
    build_name,
    degree_category,
    extract_for_paths,
    extract_studiengang,
    harmonize,
    merge_key,
    most_specific_degree,
    subject_canonicalizer,
)

__all__ = [
    "DEGREE_SPECIFICITY",
    "FUZZY_THRESHOLD",
    "Studiengang",
    "build_name",
    "degree_category",
    "extract_for_paths",
    "extract_studiengang",
    "harmonize",
    "merge_key",
    "most_specific_degree",
    "subject_canonicalizer",
]