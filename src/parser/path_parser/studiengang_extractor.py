#!/usr/bin/env python3
"""
Extrahiert Studiengänge aus den Pfaden des Vorlesungsverzeichnisses (Uni Leipzig).

Idee: Ein Pfad ist eine Liste von Knoten, z. B.
    ["Root", "SoSe 2025", "06 - Fakultät ...", "Institut für Soziologie",
     "B.A. Soziologie", "2. Fachsemester", "Pflichtmodule"]
Der Studiengang steht auf wechselnder Ebene. Statt einer festen Ebene
suchen wir den ERSTEN Knoten von oben, der wie ein Studiengang aussieht
("Studiengang-Signal"), und überspringen alles davor (Institute, Ebenen-
Container wie "Bachelor") sowie alles danach (Semester, Pflichtmodule, ...).

Benutzung:
    python studiengang_extractor.py path-fields.json            # Bericht
    python studiengang_extractor.py path-fields.json --out out  # + CSV/JSON

    from studiengang_extractor import extract_for_paths
    extract_for_paths(item["path"])   # item["path"] = Liste von Pfaden eines Moduls
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Optional, Sequence

# ============================================================================
# 1. KONFIGURATION – hier wird angepasst, wenn die Uni neue Schreibweisen erfindet
# ============================================================================

TERM_RE = re.compile(r"^(WiSe|SoSe)\s*\d{4}(/\d{2,4})?$", re.I)          # "WiSe 2025/26"
FACULTY_NO_RE = re.compile(r"^\d{2}\s*-\s*")                              # "06 - "
MODULE_RE = re.compile(r"\b\d{2}-[A-Z0-9]{2,}(?:-[A-Z0-9]+)+\b")          # "07-101-2101", "01-REL-ST063"

# Knoten direkt unter "Root/Semester", die selbst KEINE Fakultät mit Studiengängen sind
UNIT_RULES = [
    (re.compile(r"^Wahlbereich", re.I), "wahlbereich"),
    (re.compile(r"^Austauschstudium", re.I), "austausch"),
    (re.compile(r"Schlüsselqualifikation", re.I), "service"),
    (re.compile(r"Sprachenzentrum|Studienkolleg|Zentrum für Lehrer", re.I), "service"),
]

# Knoten irgendwo innerhalb einer Fakultät, die KEIN Studiengang sind
NODE_RULES = [
    (re.compile(r"Erasmus|Exchange|Austausch", re.I), "austausch"),
    (re.compile(r"^Wahlbereich", re.I), "wahlbereich"),
    (re.compile(r"Fachsprachenschein|Sprachenzentrum|Schlüsselqualifikation|\bSQ-Module|Seniorenstudium", re.I), "service"),
]

# Reine Ebenen-Container: "Bachelor", "Master", "Staatsexamen", "Studienniveau Master"
LEVEL_CONTAINER_RE = re.compile(r"^(?:Studienniveau\s+)?(Bachelor|Master|Staatsexamen)\s*$", re.I)

# Knoten, die Institute/Bereiche sind (nie ein Studiengang, auch nicht im Fallback)
INSTITUTE_RE = re.compile(r"\b(Institut|Institute|Seminar)\b", re.I)
# Sammelknoten, die zwar ein Studiengangs-Wort enthalten, aber nur gruppieren ("Wahlfächer 60 LP")
GENERIC_CONTAINER_RE = re.compile(r"^(?:Wahlfächer\b|Studiengänge anderer Fakultäten|Für Studierende)", re.I)

# Knoten, die Studienverlauf/Modulgruppen beschreiben -> hier endet die Suche
NOISE_RE = re.compile(
    r"semester|\bFS\b|\d\.\s?FS|Modulangebot|Modulübersicht|Pflicht|Wahlpflicht|Empfehlung|"
    r"Lehrveranstaltungen|Grundstudium|Hauptstudium",
    re.I,
)

# Abschluss-Signale. REIHENFOLGE ENTSCHEIDET (spezifisch vor allgemein).
# Zu jedem Label: (Label, Regex). Tippfehler aus den echten Daten sind eingebaut
# ("Master of Sience", "Staatxexamen").
_END = r"(?:\.|(?![A-Za-z]))"          # "B.A." oder "B.A" ohne Buchstaben dahinter; erlaubt "B.A.Ostslawisch"
DEGREES = [
    ("B.Sc.", re.compile(rf"(?<![A-Za-z])B\.\s?Sc{_END}|Bachelor\s+of\s+Sc?ience", re.I)),
    ("B.A.",  re.compile(rf"(?<![A-Za-z])B\.\s?A{_END}|Bachelor\s+of\s+Arts", re.I)),
    ("M.Sc.", re.compile(rf"(?<![A-Za-z])M\.\s?Sc{_END}|Master\s+of\s+Sc?ience", re.I)),
    ("M.A.",  re.compile(rf"(?<![A-Za-z])M\.\s?A{_END}|Master\s+of\s+Arts", re.I)),
    ("Bachelor", re.compile(r"\bBachelor", re.I)),
    ("Master", re.compile(r"\bMaster(?:\s+of)?\b", re.I)),
    ("Lehramt", re.compile(r"Lehramt\w*|\bLA\b")),
    ("Staatsexamen", re.compile(r"Staat\w*examen", re.I)),
    ("Diplom", re.compile(r"\bDiplom", re.I)),
    ("Wahlfach", re.compile(r"Wahlfach|Wahlfächer|Erweiterungsfach|Ergänzungsfach", re.I)),
]
DEGREE_CATEGORY = {"B.Sc.": "Bachelor", "B.A.": "Bachelor", "M.Sc.": "Master", "M.A.": "Master"}
DEGREE_SPECIFICITY = {"B.Sc.": 2, "B.A.": 2, "M.Sc.": 2, "M.A.": 2}   # alles andere = 1

SCHOOL_TYPES = [
    ("Grundschule", re.compile(r"Grundschul", re.I)),
    ("Oberschule", re.compile(r"Oberschul", re.I)),
    ("Gymnasium", re.compile(r"Gymnasi", re.I)),
    ("Sonderpädagogik", re.compile(r"Sonderp[äa]d", re.I)),
    ("Berufsbildende Schulen", re.compile(r"berufsbildend", re.I)),
]

VERSION_RE = re.compile(
    r"\(?\b(?:PO\s*\d{4}"
    r"|(?:alte|neue)\s+Prüfungsordnung[^)]*"
    r"|Immatrikulation\s+(?:ab|bis)\s+\S+\s*[\d/]+"
    r"|ab\s+(?:WS|WiSe|SoSe|SS)\s*[\d/]+)\)?",
    re.I,
)
FUZZY_THRESHOLD = 0.92   # Ähnlichkeit ab der zwei Fachnamen als Schreibvariante gelten
ECTS_RE = re.compile(r"(\d+)\s*(?:LP|Leistungspunkte?)\b", re.I)


# ============================================================================
# 2. Datenmodell
# ============================================================================

@dataclass
class Studiengang:
    kind: str                  # studiengang | wahlbereich | austausch | service | unklar
    name: str                  # normalisierte Anzeige-Bezeichnung
    subject: Optional[str]     # Fach/Bezeichnung ohne Abschluss, Schulart, PO
    degree: Optional[str]      # B.A. | B.Sc. | M.A. | M.Sc. | Bachelor | Master | Lehramt | ...
    school_type: Optional[str]
    ects: Optional[int]        # nur Angaben wie "60 LP" im Namen (Wahlfächer)
    version: Optional[str]     # Prüfungsordnung / Immatrikulationsjahr, unnormalisiert
    faculty: Optional[str]
    raw_label: Optional[str]   # der Pfadknoten, aus dem das Ergebnis stammt
    raw_index: Optional[int]   # Position dieses Knotens im Originalpfad
    confidence: str            # high | medium | low | none
    rule: str                  # welche Regel gegriffen hat (zum Debuggen)


# ============================================================================
# 3. Hilfsfunktionen
# ============================================================================

def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def detect_degree(label: str) -> Optional[str]:
    for name, rx in DEGREES:
        if rx.search(label):
            return name
    return None


def degree_category(degree: Optional[str]) -> Optional[str]:
    return DEGREE_CATEGORY.get(degree, degree)


def detect_school_type(label: str) -> Optional[str]:
    for name, rx in SCHOOL_TYPES:
        if rx.search(label):
            return name
    return None


def clean_path(path: Sequence[str]) -> tuple[list[str], list[int], Optional[str]]:
    """Entfernt 'Root' und das Semester. Gibt (Knoten, Originalindizes, Semester) zurück."""
    nodes, idx, term = [], [], None
    for i, raw in enumerate(path):
        n = _ws(str(raw))
        if not n:
            continue
        if i == 0 and n.lower() == "root":
            continue
        if TERM_RE.match(n):
            term = n
            continue
        nodes.append(n)
        idx.append(i)
    return nodes, idx, term


_ANY_DEGREE = "|".join(f"(?:{rx.pattern})" for _, rx in DEGREES)
_SCHOOL_PHRASE = (r"(?:Höheres\s+)?(?:(?:an|für)\s+(?:den\s+)?"
                  r"(?:Grundschulen|Oberschulen|Gymnasien|berufsbildenden\s+Schulen))")
_LEAD = re.compile(rf"^[\s,;:\-–/]*(?:{_ANY_DEGREE}|{_SCHOOL_PHRASE}|Höheres\b)", re.I)
_TRAIL = re.compile(rf"(?:{_ANY_DEGREE})[\s,;:\-–/]*$", re.I)
_AFTER_SEP = re.compile(rf"([,;(])\s*(?:{_ANY_DEGREE}|{_SCHOOL_PHRASE})", re.I)


def extract_subject(label: str) -> Optional[str]:
    """
    Fach ohne Abschluss/Schulart/PO/LP. Liefert None, wenn nichts übrig bleibt.
    Abschluss-Wörter werden nur am Anfang, am Ende oder nach Komma/Klammer entfernt –
    NICHT mitten im Namen ("Arqus Joint Master in European Studies" bleibt intakt).
    """
    s = VERSION_RE.sub(" ", label)
    s = re.sub(r"\(\s*\d+\s*(?:LP|Leistungspunkte?)\s*\)|\b\d+\s*(?:LP|Leistungspunkte?)\b", " ", s, flags=re.I)

    # Fall "Fach, Abschluss ..." -> alles vor dem Komma, das direkt vor dem ersten Abschluss steht
    first = None
    for _, rx in DEGREES:
        m = rx.search(s)
        if m and (first is None or m.start() < first):
            first = m.start()
    if first is not None and first > 0 and re.search(r",\s*$", s[:first]):
        s = s[:first]

    # Klammern, die Abschluss oder Schulart enthalten, komplett entfernen
    def drop_paren(m: re.Match) -> str:
        inner = m.group(1)
        return " " if (detect_degree(inner) or detect_school_type(inner)) else m.group(0)
    s = re.sub(r"\(([^)]*)\)", drop_paren, s)

    # Randständige Abschluss-/Schulart-Wörter iterativ abschälen
    for _ in range(10):
        before = s
        s = _LEAD.sub("", s)
        s = _TRAIL.sub("", s)
        s = _AFTER_SEP.sub(r"\1 ", s)
        s = re.sub(r"\(\s*[,;:\-–]*\s*\)", " ", s)              # leere Klammern
        s = _ws(s)
        if s == before:
            break

    s = re.sub(r"^Module\s+(?:der|des|im)\s+", "", s, flags=re.I)     # "Module der Volkswirtschaftslehre"
    s = s.strip(" ,;:-–/")
    return s or None


def build_name(subject, degree, school_type, ects, version) -> str:
    extras = [x for x in (degree, school_type, f"{ects} LP" if ects else None) if x]
    if subject:
        base = subject
    else:                                    # Fach nicht im Pfad erkennbar (z. B. "Staatsexamen Lehramt an Gymnasien")
        base, extras = " ".join(x for x in (degree, school_type) if x) or "?", []
        extras = [f"{ects} LP"] if ects else []
    if version:
        extras.append(version)
    return f"{base} ({', '.join(extras)})" if extras else base


def _strip_faculty(unit: str) -> str:
    return FACULTY_NO_RE.sub("", unit)


# ============================================================================
# 4. Kernalgorithmus (ein Pfad -> ein Ergebnis)
# ============================================================================

def _make_program(nodes, idxs, i, unit, level, confidence, rule) -> Studiengang:
    label = nodes[i]
    degree = detect_degree(label) or level or detect_degree(unit)   # Abschluss vom Knoten, sonst vom Container, sonst von der Einheit
    subject = extract_subject(label)
    if level and not detect_degree(label):
        subject = subject or label

    # Prüfungsordnung: im Knoten selbst, sonst im direkt folgenden Knoten (wenn der mit dem Fach beginnt)
    vm = VERSION_RE.search(label)
    if not vm and i + 1 < len(nodes) and not MODULE_RE.search(nodes[i + 1]):
        nxt = nodes[i + 1]
        if subject and nxt.casefold().startswith(subject.casefold()):
            vm = VERSION_RE.search(nxt)
    version = re.sub(r"\bseit\b", "ab", _ws(vm.group(0).strip("() ")), flags=re.I) if vm else None

    # Schulart nur bei Lehramt: eigener Knoten hat Vorrang, dann die nächsten zwei Knoten
    school = None
    if degree_category(degree) in ("Lehramt", "Staatsexamen"):
        for j in range(i, min(i + 3, len(nodes))):
            if MODULE_RE.search(nodes[j]):
                break
            school = detect_school_type(nodes[j])
            if school:
                break
        if school and subject and school.casefold() == subject.casefold():
            subject = None                    # "Lehramt Sonderpädagogik": das ist die Schulart, kein Fach

    em = ECTS_RE.search(label)
    ects = int(em.group(1)) if em else None
    return Studiengang(
        kind="studiengang",
        name=build_name(subject, degree, school, ects, version),
        subject=subject, degree=degree, school_type=school, ects=ects, version=version,
        faculty=_strip_faculty(unit), raw_label=label, raw_index=idxs[i],
        confidence=confidence, rule=rule,
    )


def _make_other(kind, parts, unit, raw_label, raw_index, rule) -> Studiengang:
    return Studiengang(
        kind=kind, name=" / ".join(_strip_faculty(p) for p in parts),
        subject=None, degree=None, school_type=None, ects=None, version=None,
        faculty=_strip_faculty(unit), raw_label=raw_label, raw_index=raw_index,
        confidence="high", rule=rule,
    )


def extract_studiengang(path: Sequence[str]) -> Studiengang:
    """Extrahiert den Studiengang (bzw. die Zuordnung) aus EINEM Pfad."""
    nodes, idxs, _term = clean_path(path)
    if not nodes:
        return Studiengang(kind="unklar", name="", subject=None, degree=None, school_type=None, ects=None,
                           version=None, faculty=None, raw_label=None, raw_index=None,
                           confidence="none", rule="leerer Pfad")

    unit, tail, tail_idx = nodes[0], nodes[1:], idxs[1:]
    nodes_t, idxs_t = tail, tail_idx

    # --- Schritt A: Sondereinheiten (Wahlbereich, Austausch, Sprachenzentrum, SQ ...)
    for rx, kind in UNIT_RULES:
        if rx.search(unit):
            parts = [unit]
            for n in tail[:2]:
                if MODULE_RE.search(n):
                    break
                parts.append(n)
                if not re.match(r"^Studienniveau", n, re.I):
                    break
            return _make_other(kind, parts, unit, unit, idxs[0], f"unit-rule:{kind}")

    # --- Schritt B: von oben nach unten den ersten Studiengang-Knoten suchen
    level: Optional[str] = None
    fallback: Optional[int] = None
    for i, node in enumerate(nodes_t):
        if MODULE_RE.search(node):                                    # Modul-Blatt erreicht
            break
        for rx, kind in NODE_RULES:                                   # Erasmus, Wahlbereich, ...
            if rx.search(node):
                return _make_other(kind, [node], unit, node, idxs_t[i], f"node-rule:{kind}")

        m = LEVEL_CONTAINER_RE.match(node)
        if m:                                                          # "Bachelor"/"Master"/"Staatsexamen"
            level = m.group(1).capitalize()
            continue

        degree = detect_degree(node)
        if degree and not GENERIC_CONTAINER_RE.match(node):            # eindeutiges Studiengang-Signal
            return _make_program(nodes_t, idxs_t, i, unit, level, "high", "abschluss-signal")

        if GENERIC_CONTAINER_RE.match(node) or (INSTITUTE_RE.search(node) and not degree):
            continue                                                   # Institut / Sammelknoten überspringen
        if NOISE_RE.search(node):                                      # Semester / Pflichtmodule -> Ende
            break
        if level:                                                      # erster Knoten nach "Bachelor"/"Master"
            return _make_program(nodes_t, idxs_t, i, unit, level, "medium", "nach-ebenen-container")
        if fallback is None:
            fallback = i

    # --- Schritt C: Fallback = erster "neutraler" Knoten vor dem Semester-/Modulteil
    if fallback is not None:
        return _make_program(nodes_t, idxs_t, fallback, unit, None, "low", "fallback-erster-knoten")

    return Studiengang(kind="unklar", name="", subject=None, degree=None, school_type=None, ects=None,
                       version=None, faculty=_strip_faculty(unit), raw_label=None, raw_index=None,
                       confidence="none", rule="kein Studiengang im Pfad (nur Institut/Fakultät)")


# ============================================================================
# 5. Auf ein Modul (mehrere Pfade) anwenden + Schreibweisen vereinheitlichen
# ============================================================================

def extract_for_paths(paths: Sequence[Sequence[str]]) -> list[Studiengang]:
    """Alle Pfade EINES Moduls -> deduplizierte Liste der Studiengänge/Zuordnungen."""
    seen, out = set(), []
    for p in paths:
        r = extract_studiengang(p)
        key = (r.kind, r.name, r.faculty)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _merge_key(r: Studiengang):
    return (r.kind, (r.subject or "").casefold(), degree_category(r.degree),
            r.school_type, r.ects, (r.version or "").casefold(), r.faculty)


# Öffentliche Bausteine für die Streaming-Harmonisierung (siehe degree_parser.py).
# Sie kapseln dieselben Regeln wie harmonize(), arbeiten aber auf Zählungen statt
# auf der vollständigen Ergebnisliste, damit kein großer Speicherbedarf entsteht.

def merge_key(r: Studiengang):
    """Öffentlicher Alias von _merge_key für externe Aufrufer."""
    return _merge_key(r)


def most_specific_degree(degrees) -> Optional[str]:
    """Spezifischster Abschluss einer Gruppe (höchste DEGREE_SPECIFICITY)."""
    return max(degrees, key=lambda d: DEGREE_SPECIFICITY.get(d, 1))


def subject_canonicalizer(by_ctx_counts):
    """
    Aus Zählungen pro (Fakultät, Abschluss-Kategorie) eine Abbildung
    Schreibweise -> kanonische Schreibweise erzeugen (gleiche Fuzzy-Regel wie harmonize()).

    by_ctx_counts: dict[(faculty, category)] -> Counter[subject] -> Anzahl
    Rückgabe:      dict[(faculty, category)] -> dict[subject] -> canonical_subject
    """
    out: dict = {}
    for ctx, freq in by_ctx_counts.items():
        canon: dict = {}
        for subj, _ in freq.most_common():                      # häufigste zuerst
            match = next((c for c in canon.values()
                          if difflib.SequenceMatcher(None, subj.casefold(), c.casefold()).ratio() >= FUZZY_THRESHOLD), None)
            canon[subj] = match or subj
        out[ctx] = canon
    return out


def harmonize(all_results: Sequence[Studiengang]) -> None:
    """
    Gleicht Varianten desselben Studiengangs an ("Bachelor Soziologie" vs. "B.A. Soziologie"):
    Innerhalb einer Gruppe gleichen Fachs/Fakultät/Kategorie wird der spezifischste Abschluss übernommen.
    Verändert die Objekte in place.
    """
    groups: dict = defaultdict(list)
    for r in all_results:
        if r.kind == "studiengang" and r.subject:
            groups[_merge_key(r)].append(r)
    for rs in groups.values():
        best = most_specific_degree(r.degree for r in rs)
        for r in rs:
            if r.degree != best:
                r.degree = best
                r.name = build_name(r.subject, r.degree, r.school_type, r.ects, r.version)

    # Tippfehler/Leerzeichen-Varianten ("Geopgraphie", "Diplom/ Kirchliches"): sehr ähnliche Fächer
    # innerhalb derselben Fakultät + Abschluss-Kategorie auf die häufigste Schreibweise vereinheitlichen
    by_ctx: dict = defaultdict(list)
    for r in all_results:
        if r.kind == "studiengang" and r.subject:
            by_ctx[(r.faculty, degree_category(r.degree))].append(r)
    counts = {ctx: Counter(r.subject for r in rs) for ctx, rs in by_ctx.items()}
    canonical = subject_canonicalizer(counts)
    for ctx, rs in by_ctx.items():
        canon = canonical[ctx]
        for r in rs:
            if canon[r.subject] != r.subject:
                r.subject = canon[r.subject]
                r.name = build_name(r.subject, r.degree, r.school_type, r.ects, r.version)


# ============================================================================
# 7. Selbsttest (python studiengang_extractor.py --selftest)
# ============================================================================

_TESTS = [
    # (Pfad ab Fakultät, erwarteter Name, erwartete kind)
    (["06 - Fakultät für Sozialwissenschaften und Philosophie", "Institut für Soziologie", "B.A. Soziologie", "2. Fachsemester", "Pflichtmodule"],
     "Soziologie (B.A.)", "studiengang"),
    (["03 - Fakultät für Geschichte, Kunst- und Regionalwissenschaften", "Historisches Seminar", "Geschichte, Lehramt", "Staatsexamen Lehramt an Gymnasien"],
     "Geschichte (Lehramt, Gymnasium)", "studiengang"),
    (["10 - Fakultät für Mathematik und Informatik", "Informatik", "Informatik (Master of Sience)", "1. Semester"],
     "Informatik (M.Sc.)", "studiengang"),
    (["12 - Fakultät für Physik und Erdsystemwissenschaften", "Bachelor", "Geographie", "2. Semester"],
     "Geographie (Bachelor)", "studiengang"),
    (["07 - Wirtschaftswissenschaftliche Fakultät", "Bachelor", "Wirtschaftsinformatik", "Wirtschaftsinformatik (alte Prüfungsordnung)", "Pflichtmodule"],
     "Wirtschaftsinformatik (Bachelor, alte Prüfungsordnung)", "studiengang"),
    (["04 - Philologische Fakultät", "Institut für Slawistik", "B.A.Ostslawische Sprachen, Literaturen und Kulturen", "Wahlpflichtbereich"],
     "Ostslawische Sprachen, Literaturen und Kulturen (B.A.)", "studiengang"),
    (["04 - Philologische Fakultät", "Institut für Slawistik", "Wahlfächer 60 LP", "Wahlfach Polonistik 60 LP", "Fachmodule"],
     "Polonistik (Wahlfach, 60 LP)", "studiengang"),
    (["06 - Fakultät für Sozialwissenschaften und Philosophie", "Institut für Philosophie", "Modules for Exchanges Students of Philosophy", "Master Modules"],
     "Modules for Exchanges Students of Philosophy", "austausch"),
    (["Wahlbereich der Geistes- und Sozialwissenschaften", "Afrikastudien"],
     "Wahlbereich der Geistes- und Sozialwissenschaften / Afrikastudien", "wahlbereich"),
    (["30 - Sprachenzentrum", "Arabisch"], "Sprachenzentrum / Arabisch", "service"),
    (["04 - Philologische Fakultät", "Institut für Klassische Philologie und Komparatistik"], "", "unklar"),
    (["01 - Theologische Fakultät", "Modul 01-SQM-20 (Lehramt Ethik/ Philosophie)"], "", "unklar"),
]


def selftest() -> None:
    bad = 0
    for tail, want_name, want_kind in _TESTS:
        r = extract_studiengang(["Root", "SoSe 2025", *tail])
        ok = (r.name, r.kind) == (want_name, want_kind)
        bad += not ok
        print(("OK   " if ok else "FAIL ") + " / ".join(tail[-2:]) + f"  ->  {r.name!r} [{r.kind}]"
              + ("" if ok else f"   erwartet: {want_name!r} [{want_kind}]"))
    print("\nalle Tests bestanden" if not bad else f"\n{bad} Test(s) fehlgeschlagen")
    raise SystemExit(1 if bad else 0)


# ============================================================================
# 6. Kommandozeile: gesamte JSON verarbeiten + Prüfbericht
# ============================================================================

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("json_file", nargs="?")
    ap.add_argument("--out", help="Präfix für Ausgabedateien (erzeugt <out>_modules.json, <out>_studiengaenge.csv)")
    ap.add_argument("--no-harmonize", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
    if not args.json_file:
        ap.error("json_file fehlt")

    with open(args.json_file, encoding="utf-8") as f:
        items = json.load(f)["items"]

    per_item = [extract_for_paths(it["path"]) for it in items]
    flat = [r for rs in per_item for r in rs]
    if not args.no_harmonize:
        harmonize(flat)
        for rs in per_item:                                   # nach Harmonisierung erneut deduplizieren
            seen, keep = set(), []
            for r in rs:
                k = (r.kind, r.name, r.faculty)
                if k not in seen:
                    seen.add(k); keep.append(r)
            rs[:] = keep
        flat = [r for rs in per_item for r in rs]             # nach dem Deduplizieren neu aufbauen (sonst zählt die CSV doppelt)

    print(f"Module: {len(items)}")
    print("kind:      ", dict(Counter(r.kind for rs in per_item for r in rs)))
    print("confidence:", dict(Counter(r.confidence for rs in per_item for r in rs)))
    print("Module ohne Studiengang:", sum(1 for rs in per_item if not any(r.kind == "studiengang" for r in rs)))

    programs = defaultdict(set)
    for rs in per_item:
        for r in rs:
            if r.kind == "studiengang":
                programs[r.faculty].add(r.name)
    print(f"\nEindeutige Studiengänge: {len(set(n for s in programs.values() for n in s))}")

    for label, cond in (("LOW-CONFIDENCE (bitte prüfen)", lambda r: r.confidence == "low"),
                        ("MEDIUM (nach Ebenen-Container)", lambda r: r.confidence == "medium"),
                        ("UNKLAR (kein Studiengang gefunden)", lambda r: r.kind == "unklar")):
        c = Counter((r.faculty, r.raw_label, r.name, r.rule) for r in flat if cond(r))
        print(f"\n--- {label}: {len(c)} verschiedene ---")
        for (fac, raw, name, rule), n in sorted(c.items(), key=lambda x: str(x[0]))[:40]:
            print(f"  {n:4d}x [{fac}] {raw or '-'}  ->  {name or '-'}   ({rule})")

    if args.out:
        with open(f"{args.out}_modules.json", "w", encoding="utf-8") as f:
            json.dump([{"index": i, "studiengaenge": [asdict(r) for r in rs]} for i, rs in enumerate(per_item)],
                      f, ensure_ascii=False, indent=1)
        agg = Counter((r.kind, r.faculty, r.name, r.degree, r.subject, r.school_type, r.version, r.confidence)
                      for r in flat)
        with open(f"{args.out}_studiengaenge.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["kind", "faculty", "name", "degree", "subject", "school_type", "version", "confidence", "anzahl_module"])
            for k, n in sorted(agg.items(), key=lambda x: (x[0][0], str(x[0][1]), x[0][2])):
                w.writerow([*("" if v is None else v for v in k), n])
        print(f"\nGeschrieben: {args.out}_modules.json, {args.out}_studiengaenge.csv")


if __name__ == "__main__":
    main()
