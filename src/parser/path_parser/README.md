# Studiengang-Extraktor für das Vorlesungsverzeichnis der Universität Leipzig

Extrahiert aus den Pfaden, die ein Crawler im öffentlichen Vorlesungsverzeichnis aufzeichnet, den
zugehörigen **Studiengang** (bzw. die Zuordnung, wenn es kein Studiengang ist) und vereinheitlicht
die Schreibweisen.

> **Bitte zuerst lesen:** Dieses Projekt wurde mit Hilfe einer KI erstellt und nur an **einem**
> Datenstand getestet. Siehe [KI-Disclaimer](#ki-disclaimer) und [Einschränkungen](#einschränkungen).

---

## Inhalt

1. [Das Problem](#das-problem)
2. [Dateien](#dateien)
3. [Schnellstart](#schnellstart)
4. [Ein- und Ausgabeformat](#ein--und-ausgabeformat)
5. [Funktionsweise im Detail](#funktionsweise-im-detail)
6. [Konfiguration und Erweiterung](#konfiguration-und-erweiterung)
7. [Ergebnisse auf dem Testdatensatz](#ergebnisse-auf-dem-testdatensatz)
8. [Einschränkungen](#einschränkungen)
9. [Wartung: neue Semester prüfen](#wartung-neue-semester-prüfen)
10. [KI-Disclaimer](#ki-disclaimer)
11. [Lizenz](#lizenz)

---

## Das Problem

Ein Pfad ist eine Liste von Knoten, zum Beispiel:

```
Root / SoSe 2025 / 06 - Fakultät für Sozialwissenschaften und Philosophie /
Institut für Soziologie / B.A. Soziologie / 2. Fachsemester / Pflichtmodule
```

Der Studiengang steht darin **nicht auf einer festen Ebene** und **nicht in einem festen Format**:

| Muster im Pfad | Beispiel |
|---|---|
| direkt unter der Fakultät | `08 - Sport / B.Sc. Sportmanagement (PO 2025) / 2. Fachsemester` |
| unter einem Institut | `04 - Philologie / Institut für Anglistik / Anglistik, Bachelor of Arts / …` |
| unter einem Ebenen-Container, ohne Abschluss im Namen | `12 - Physik / Bachelor / Geographie / 2. Semester` |
| doppelt gestaffelt | `04 - Philologie / Institut für Slawistik / Wahlfächer 60 LP / Wahlfach Polonistik 60 LP / …` |
| Abschluss vorn, hinten oder in Klammern | `B.A. Soziologie`, `Soziologie, Bachelor`, `Informatik (Bachelor of Science)` |
| gar kein Studiengang | Sprachenzentrum, Schlüsselqualifikationen, Erasmus, Wahlbereich, reine Institutspfade |
| Modul steht selbst im Pfad | `07 - … / Master / Module der BWL / 07-201-1103 Landscape Management (5 LP)` |

Dazu kommen Tippfehler in den Originaldaten (`Master of Sience`, `Staatxexamen`,
`Wirtschafts- und Sozialgeopgraphie`, `B.A.Ostslawische …` ohne Leerzeichen) und mehrere Schreibweisen
für dasselbe (`B.A. Soziologie` / `Bachelor Soziologie`, `seit WiSe 24/25` / `ab WiSe 24/25`).

---

## Dateien

| Datei | Inhalt |
|---|---|
| `studiengang_extractor.py` | Der Extraktor (Python-Standardbibliothek, keine Zusatzpakete). Enthält Konfiguration, Algorithmus, CLI und Selbsttest. |
| `ergebnis_studiengaenge.csv` | Aggregierte Liste aller erkannten Studiengänge/Zuordnungen mit Anzahl Module (Trennzeichen `;`, UTF-8 mit BOM, für Excel). |
| `ergebnis_modules.json` | Ergebnis pro Modul (Index in `items`), inkl. Debug-Felder (`rule`, `confidence`, `raw_label`, `raw_index`). |
| `README.md` | Diese Datei. |

Voraussetzung: Python 3.9 oder neuer.

---

## Schnellstart

**Kommandozeile**

```bash
# Prüfbericht auf der Konsole
python studiengang_extractor.py path-fields.json

# zusätzlich CSV und JSON schreiben
python studiengang_extractor.py path-fields.json --out ergebnis

# ohne Vereinheitlichung der Schreibweisen (Rohergebnis)
python studiengang_extractor.py path-fields.json --no-harmonize

# Selbsttest der Regeln (12 Randfälle)
python studiengang_extractor.py --selftest
```

**Als Bibliothek**

```python
# Innerhalb des Projekts ist das Modul als Package importierbar (Verzeichnis path_parser):
from parser.path_parser import extract_for_paths, extract_studiengang, harmonize

# Alternativ direkt aus dem Ordner heraus:
from studiengang_extractor import extract_for_paths, extract_studiengang

# alle Pfade EINES Moduls -> deduplizierte Liste
for sg in extract_for_paths(item["path"]):
    print(sg.kind, sg.name, sg.confidence)

# einen einzelnen Pfad untersuchen (zum Debuggen)
r = extract_studiengang(["Root", "SoSe 2025", "12 - Fakultät für Physik …", "Bachelor", "Physik", "2. Semester"])
print(r.name, r.rule, r.confidence)      # Physik (Bachelor)  nach-ebenen-container  medium
```

Hinweis: `harmonize()` (Zusammenführen von Schreibvarianten) arbeitet auf der **Gesamtmenge** aller Ergebnisse
und wird nur von der CLI automatisch aufgerufen. Wer die Bibliothek nutzt, ruft es selbst mit einer flachen
Liste aller `Studiengang`-Objekte auf (es verändert diese in place).

Für große Datenmengen (Streaming, ohne alle Ergebnisse im Speicher zu halten) stellt das Modul zusätzlich die
Bausteine `merge_key()`, `most_specific_degree()` und `subject_canonicalizer()` bereit: Sie kapseln dieselben
Regeln wie `harmonize()`, arbeiten aber auf Zählungen. Genutzt werden sie von `src/parser/degree_parser.py`, das
als zweiter Durchlauf die Studiengänge aus den Modulpfaden der Datenbank extrahiert, harmonisiert und als
`Degree`-Datensätze verknüpft (siehe `python -m src.parser.degree_parser`).

---

## Ein- und Ausgabeformat

### Eingabe

```json
{
  "count": 1575, "page": 1, "limit": 1575, "total_pages": 1,
  "items": [
    { "path": [
        ["Root", "SoSe 2025", "01 - Theologische Fakultät", "B.A. Judentum in Tradition und Gegenwart"],
        ["Root", "SoSe 2025", "01 - Theologische Fakultät", "Evangelische Theologie (Diplom/ Kirchliches Examen)", "Modulübersichten", "Grundstudium"]
    ]}
  ]
}
```

Jedes Element von `items` ist ein Modul mit **einem oder mehreren** Pfaden. Die Datei enthält keine Modul-ID;
die Ausgabe verwendet deshalb die Position in `items` als `index`.

Erwartete Annahmen: Der erste Knoten ist `Root`, der zweite ein Semester (`SoSe 2025`, `WiSe 2025/26`), der
dritte die „Einheit“ (meist eine Fakultät).

### Ausgabe (ein `Studiengang`-Objekt)

| Feld | Bedeutung |
|---|---|
| `kind` | `studiengang`, `wahlbereich`, `austausch`, `service` oder `unklar` |
| `name` | vereinheitlichte Bezeichnung, z. B. `Geschichte (Lehramt, Gymnasium)` |
| `subject` | Fach/Bezeichnung ohne Abschluss, Schulart, Prüfungsordnung, LP |
| `degree` | `B.A.`, `B.Sc.`, `M.A.`, `M.Sc.`, `Bachelor`, `Master`, `Lehramt`, `Staatsexamen`, `Diplom`, `Wahlfach` |
| `school_type` | nur bei Lehramt: Grundschule, Oberschule, Gymnasium, Sonderpädagogik, Berufsbildende Schulen |
| `ects` | Umfang aus dem Namen, z. B. `60` bei „Wahlfach (60 LP)“ |
| `version` | Prüfungsordnung/Immatrikulationsangabe, z. B. `PO 2017`, `Immatrikulation ab WiSe 2024/25` |
| `faculty` | Fakultät/Einheit ohne Nummernpräfix |
| `raw_label` | der Pfadknoten, aus dem das Ergebnis stammt |
| `raw_index` | Position dieses Knotens im **Originalpfad** (inkl. `Root` und Semester) |
| `confidence` | `high`, `medium`, `low`, `none` (siehe unten) |
| `rule` | welche Regel gegriffen hat (`abschluss-signal`, `nach-ebenen-container`, `fallback-erster-knoten`, `unit-rule:…`, `node-rule:…`) |

Aufbau von `name`:

```
{subject} ({degree}, {school_type}, {ects} LP, {version})        z. B. Musikwissenschaft (Wahlfach, 60 LP)
{degree} {school_type} ({version})                                 wenn kein Fach erkennbar: Lehramt Gymnasium (PO 2017)
```

### CSV-Spalten

`kind; faculty; name; degree; subject; school_type; version; confidence; anzahl_module`

`anzahl_module` zählt, in wie vielen Modulen diese Kombination vorkommt (pro Modul einmal). Weil `confidence`
Teil des Gruppenschlüssels ist, kann derselbe Studiengang in mehreren Zeilen auftauchen, wenn er über
unterschiedlich sichere Regeln gefunden wurde.

---

## Funktionsweise im Detail

### Grundidee

Statt eine feste Ebene auszulesen, sucht der Algorithmus **von oben nach unten den ersten Knoten, der wie
ein Studiengang aussieht**. Alles davor (Institute, Ebenen-Container) wird übersprungen, alles danach
(Semester, Pflichtmodule, Fächerkooperationen) ignoriert.

### Schritt 0 – Pfad bereinigen (`clean_path`)

- `Root` (nur an Position 0) und der Semesterknoten (`^(WiSe|SoSe) \d{4}(/\d{2,4})?$`) werden entfernt.
- Whitespace wird normalisiert, leere Knoten entfallen.
- Der erste verbleibende Knoten ist die **Einheit** (`unit`), der Rest der **Rest-Pfad** (`tail`).
- Das Semester wird erkannt, aber **nicht in die Ausgabe übernommen** (siehe Einschränkungen).

### Schritt 1 – Sondereinheiten (`UNIT_RULES`)

Passt die Einheit auf eines dieser Muster, wird sofort ein Nicht-Studiengang zurückgegeben:

| Muster | `kind` |
|---|---|
| `Wahlbereich…` | `wahlbereich` |
| `Austauschstudium…` | `austausch` |
| `…Schlüsselqualifikation…` | `service` |
| `Sprachenzentrum`, `Studienkolleg`, `Zentrum für Lehrer…` | `service` |

Der Name besteht aus der Einheit plus dem ersten Folgeknoten (bei „Studienniveau Bachelor/Master“ aus den
ersten zwei), aber nie über einen Modulcode hinaus.
Beispiel: `Sprachenzentrum / Arabisch`, `Austauschstudium … / Studienniveau Bachelor / Anglistik`.

### Schritt 2 – Rest-Pfad von oben nach unten durchlaufen

Für jeden Knoten werden die folgenden Prüfungen **in genau dieser Reihenfolge** angewendet; die erste
zutreffende entscheidet:

| # | Prüfung | Wirkung |
|---|---|---|
| 1 | Knoten enthält **Modulcode** (`\d{2}-[A-Z0-9]{2,}(-[A-Z0-9]+)+`, z. B. `07-101-2101`, `01-REL-ST063`) | Suche endet (Blatt erreicht) |
| 2 | Treffer in `NODE_RULES` (`Erasmus`, `Exchange`, `Austausch`, `Wahlbereich…`, `Fachsprachenschein`, `Sprachenzentrum`, `Schlüsselqualifikation`, `SQ-Module`, `Seniorenstudium`) | Rückgabe als `austausch` / `wahlbereich` / `service` |
| 3 | Knoten ist **reiner Ebenen-Container** (`Bachelor`, `Master`, `Staatsexamen`, ggf. mit „Studienniveau“) | Ebene merken, weiter |
| 4 | Knoten enthält ein **Abschluss-Signal** und ist kein Sammelknoten | **Studiengang gefunden**, `confidence = high` |
| 5 | Knoten ist Sammelknoten (`Wahlfächer…`, `Studiengänge anderer Fakultäten`, `Für Studierende…`) oder ein **Institut** (`Institut`, `Institute`, `Seminar`) ohne Abschluss-Signal | überspringen |
| 6 | Knoten sieht nach **Studienverlauf/Modulgruppe** aus (`semester`, `FS`, `Pflicht`, `Wahlpflicht`, `Modulangebot`, `Empfehlung`, `Lehrveranstaltungen`, `Grundstudium`, `Hauptstudium`) | Suche endet |
| 7 | Es wurde zuvor ein Ebenen-Container gemerkt | Dieser Knoten ist der Studiengang, `confidence = medium` |
| 8 | sonst | als **Fallback-Kandidat** merken (nur der erste) |

Wird die Schleife beendet, ohne dass ein Studiengang gefunden wurde:

- Fallback-Kandidat vorhanden → dieser wird zurückgegeben, `confidence = low`.
- sonst → `kind = unklar`, `confidence = none` (Pfad enthält nur Institut/Fakultät).

Wichtig: Die Prüfungen 2 und 4 stehen in dieser Reihenfolge. Ein Knoten wie `Modules for Exchange Students …
Master Modules` wird daher als `austausch` erkannt und nicht als Master-Studiengang.

### Abschluss-Signale (`DEGREES`)

Die **Reihenfolge der Liste entscheidet**: das erste Label, dessen Regex passt, wird `degree`.

| Reihenfolge | Label | erkennt u. a. |
|---|---|---|
| 1 | `B.Sc.` | `B.Sc.`, `B. Sc.`, `Bachelor of Science` |
| 2 | `B.A.` | `B.A.`, `B.A.Ostslawische…`, `Bachelor of Arts` |
| 3 | `M.Sc.` | `M.Sc.`, `M. Sc.`, `Master of Science`, `Master of Sience` (Tippfehler) |
| 4 | `M.A.` | `M.A.`, `Master of Arts` |
| 5 | `Bachelor` | `Bachelor…` |
| 6 | `Master` | `Master`, `Master of …` |
| 7 | `Lehramt` | `Lehramt…`, `Lehramtsstudiengänge`, `LA` |
| 8 | `Staatsexamen` | `Staatsexamen`, `Staatxexamen` (Tippfehler) |
| 9 | `Diplom` | `Diplom…` |
| 10 | `Wahlfach` | `Wahlfach`, `Wahlfächer`, `Erweiterungsfach`, `Ergänzungsfach` |

Folgen der Reihenfolge: „Staatsexamen Lehramt an Gymnasien“ ergibt `Lehramt` (nicht `Staatsexamen`);
„Staatsexamen Lehramt an Oberschulen, Erweiterungsfach Russisch“ ergibt ebenfalls `Lehramt`.

Kommt kein Signal im Knoten vor, wird `degree` in dieser Reihenfolge **geerbt**: gemerkter Ebenen-Container →
Label der Einheit (deshalb erhält die Zittau/Görlitz-Kooperation „Lehramt“).

### Schritt 3 – Felder aus dem Knoten ableiten (`_make_program`)

**Fach (`subject`, `extract_subject`).** Aus dem Knotentext werden nacheinander entfernt:

1. Prüfungsordnungs-Angaben (`VERSION_RE`) und LP-Angaben (`60 LP`, `(30 Leistungspunkte)`).
2. Bei der Form `Fach, Abschluss …` alles ab dem Komma direkt vor dem ersten Abschluss.
3. Klammern, die einen Abschluss oder eine Schulart enthalten (`(Bachelor of Science)`, `(Gymnasium)`, `(Lehramt)`).
4. Abschluss-, Schulart- und „Höheres“-Wörter, **aber nur am Anfang, am Ende oder direkt nach Komma/Klammer**
   (iterativ). So bleibt „Arqus Joint **Master** in European Studies“ intakt.
5. Ein führendes „Module der/des/im“ (`Module der Volkswirtschaftslehre` ergibt `Volkswirtschaftslehre`).

Bleibt nichts übrig, ist `subject = None` (typisch bei „Staatsexamen Lehramt an Gymnasien (PO 2017)“).

**Schulart (`school_type`).** Nur wenn `degree` = Lehramt oder Staatsexamen. Gesucht wird im eigenen Knoten,
dann in den nächsten zwei Knoten (nie über einen Modulcode hinaus). Erster Treffer in der Reihenfolge
Grundschule, Oberschule, Gymnasium, Sonderpädagogik, Berufsbildende Schulen. Entspricht das „Fach“ selbst der
Schulart (`Lehramt Sonderpädagogik`), wird das Fach verworfen, weil es die Schulart und kein Fach ist.

**Prüfungsordnung (`version`).** Zuerst im eigenen Knoten, sonst im direkt folgenden Knoten, **aber nur wenn
dieser mit dem Fach beginnt** (Fall `Wirtschaftsinformatik` gefolgt von `Wirtschaftsinformatik (alte
Prüfungsordnung)`). Erkannt werden `PO 2017`, `(alte|neue) Prüfungsordnung …`, `Immatrikulation ab/bis …`,
`ab WS/WiSe/SoSe 22/23`. „seit“ wird zu „ab“ vereinheitlicht, sonst bleibt der Text wie im Original.

**Umfang (`ects`).** Erste Zahl vor „LP“/„Leistungspunkte“ im Knoten.

### Schritt 4 – Modul mit mehreren Pfaden (`extract_for_paths`)

Alle Pfade eines Moduls werden einzeln ausgewertet und nach `(kind, name, faculty)` dedupliziert. Ein Modul
kann daher **mehrere** Studiengänge haben, und das ist gewollt: Es steht ja in mehreren Studienplänen.

### Schritt 5 – Vereinheitlichen (`harmonize`, optional)

Läuft über **alle** Ergebnisse, in zwei Stufen:

1. **Abschluss angleichen:** Gruppen mit gleichem Fach (ohne Groß-/Kleinschreibung), Fakultät, Abschluss-Kategorie
   (B.A./B.Sc./Bachelor ergibt „Bachelor“, M.* ergibt „Master“), Schulart, LP und Version übernehmen den
   **spezifischsten** Abschluss. Beispiel: `Bachelor Soziologie` und `B.A. Soziologie` ergeben beide `Soziologie (B.A.)`.
2. **Tippfehler angleichen:** Innerhalb derselben Fakultät und Abschluss-Kategorie werden Fachnamen mit
   Ähnlichkeit ≥ 0,92 (`difflib.SequenceMatcher`, `FUZZY_THRESHOLD`) auf die **häufigste** Schreibweise
   gezogen. Beispiel: `Wirtschafts- und Sozialgeopgraphie` ergibt `Wirtschafts- und Sozialgeographie`.

Danach werden die Ergebnisse je Modul erneut dedupliziert.

### Konfidenz

| Wert | Bedeutung | Verlässlichkeit |
|---|---|---|
| `high` | Abschluss-Signal im Knoten oder eindeutige Sonderregel | hoch |
| `medium` | erster Knoten nach `Bachelor`/`Master`/`Staatsexamen`-Container, ohne Signal im Namen | meist richtig; Knoten kann eine Modulgruppe statt eines Studiengangs sein |
| `low` | Fallback: erster „neutraler“ Knoten vor dem Semesterteil | **manuell prüfen** |
| `none` | nichts gefunden (`unklar`) | kein Studiengang ableitbar |

---

## Konfiguration und Erweiterung

Alle Regeln stehen oben in `studiengang_extractor.py` als Regex-Listen. Typische Anpassungen:

| Ziel | Wo |
|---|---|
| neue Abschlussbezeichnung (z. B. „Magister“) | `DEGREES` (Reihenfolge beachten), bei Bedarf `DEGREE_CATEGORY` |
| neue Sondereinheit (z. B. neues Zentrum) | `UNIT_RULES` |
| neuer Nicht-Studiengang innerhalb einer Fakultät | `NODE_RULES` |
| neuer Sammelknoten, der fälschlich als Studiengang gilt | `GENERIC_CONTAINER_RE` |
| neues Institut mit ungewöhnlichem Namen | `INSTITUTE_RE` |
| neue Semester-/Modulgruppen-Bezeichnung | `NOISE_RE` |
| neue Schularten | `SCHOOL_TYPES` |
| neue PO-Schreibweisen | `VERSION_RE` |
| Tippfehler-Zusammenführung strenger/lockerer | `FUZZY_THRESHOLD` |

Nach jeder Änderung: `python studiengang_extractor.py --selftest` und den Bericht auf dem echten Datensatz
ansehen. Bei neuen Sonderfällen gehört ein Testfall in die Liste `_TESTS`.

---

## Ergebnisse auf dem Testdatensatz

Datenbasis: `path-fields.json`, 1575 Module, 4059 Pfade (2052 eindeutig), Semester SoSe 2025, WiSe 2025/26,
SoSe 2026, WiSe 2026/27.

| Kennzahl | Wert |
|---|---|
| Zuordnungen Modul → Studiengang/Bereich (nach Deduplizierung) | 3776 |
| davon `studiengang` | 2995 |
| davon `wahlbereich` / `austausch` / `service` | 273 / 282 / 143 |
| davon `unklar` | 83 |
| Studiengang-Zuordnungen `high` / `medium` / `low` | 2350 / 616 / 29 |
| Module ohne Studiengang (nur Wahlbereich/Austausch/Service/unklar) | 163 |
| verschiedene Studiengang-Bezeichnungen (fakultätsübergreifend gezählt) | 252 |

Die 83 `unklar`-Zuordnungen sind Pfade, die nur bis zu einem Institut reichen (82 in der Philologischen Fakultät,
z. B. „Institut für Klassische Philologie und Komparatistik“) sowie ein Theologie-Pfad, der nur einen Modulknoten
enthält.

Diese Zahlen beschreiben den Ist-Zustand des Skripts auf dieser Datei. Sie sind **kein Maß für Korrektheit**
(siehe unten: es gibt keine Referenzdaten).

---

## Einschränkungen

### Inhaltlich

- **Zuordnung ist nicht gleich Herkunft.** Erkannt wird der Studiengang, in dessen Studienplan das Modul im
  Verzeichnis erscheint, nicht der Studiengang, der das Modul „besitzt“. Ein Soziologie-Modul unter
  „Kulturwissenschaften, Bachelor / Fächerkooperationen“ wird dem Kulturwissenschafts-Studiengang zugeordnet.
  Exportmodule (Chemie: „Studiengänge anderer Fakultäten / … / M.Sc. Mathematics“) landen beim Zielstudiengang.
- **Gruppenknoten statt Studiengang (medium).** In der Wirtschaftswissenschaftlichen Fakultät heißt es
  `Master / Module der Betriebswirtschaftslehre`. Das ist eine Modulgruppe; sie kann mehrere echte
  Master-Studiengänge bündeln, erscheint hier aber als `Betriebswirtschaftslehre (Master)`.
- **Fach fehlt teilweise bei Lehramt.** In Physik/Erdsystem und Chemie steht im Pfad nur „Staatsexamen Lehramt
  an Gymnasien (PO 2017)“ ohne Fach. Ergebnis: `Lehramt Gymnasium (PO 2017)`, unabhängig vom Fach.
- **Schulart kann ungenau sein.** Enthält ein Knoten mehrere Schularten oder Schulart-Wörter in anderer Rolle,
  gewinnt der erste Treffer in der Reihenfolge von `SCHOOL_TYPES`. Bei „Lehramt an Oberschulen mit
  Sonderpädagogik“ wäre das Oberschule. Bei der Zittau/Görlitz-Kooperation wird die Einheit nicht auf Schulart
  untersucht, daher bleibt `school_type` leer.
- **„Lehramt“ gilt als Abschluss.** Studiengänge mit „Lehramt“ und „Staatsexamen“ werden immer als `Lehramt`
  geführt; ein Unterschied zu reinen Staatsexamens-Studiengängen (z. B. Pharmazie) wird nicht abgebildet.
  Pharmazie und Hebammenkunde haben im Pfad keinen Abschluss und erscheinen ohne `degree` (Fallback, `low`).
- **Informationsverlust bei Abschluss-Wörtern.** `Evangelische Theologie (Diplom/ Kirchliches Examen)` wird zu
  `Evangelische Theologie (Diplom)`; „Kirchliches Examen“ geht verloren. `Erweiterungsfach` wird als `Wahlfach`
  geführt.
- **Aliasse und Übersetzungen werden nicht erkannt.** `Physik` und `Physics`, `IPSP`, `IPSP - 3 years
  (expiring)` und `International Physics Studies Program (Honours)`, `Deutsch als Fremd- und Zweitsprache` und
  `Deutsch als Zweit- und Fremdsprache` bleiben getrennte Einträge. Dafür wäre eine manuelle Alias-Tabelle nötig.
- **Versionsangaben sind nur minimal normalisiert.** `ab WS 23/24` und `ab WS 2023/24` bleiben verschieden.
  `Musikwissenschaft (B.A.)` und `Musikwissenschaft (B.A., ab WS 22/23)` sind vermutlich derselbe Studiengang,
  werden aber getrennt geführt. Ob zwei Prüfungsordnungen inhaltlich zusammengehören, kann der Pfad nicht sagen.
- **Modifikatoren bleiben im Fachnamen.** In `Deutsch als Fremd- und Zweitsprache, Binationaler (M.A.)` steht
  „Binationaler“ weiter im Fach.
- **Bezeichnungen sind die des Verzeichnisses**, nicht die offiziellen Studiengangsbezeichnungen der
  Studienordnungen. Das Verzeichnis kann veraltete oder unvollständige Einträge enthalten.
- **Semester geht verloren.** Es wird beim Bereinigen erkannt, aber nicht ausgegeben. Der Extraktor kann daher
  nicht sagen, in welchem Semester ein Studiengang ein Modul führte. Das Feld ließe sich leicht ergänzen (der
  Wert `_term` wird in `extract_studiengang` bereits berechnet).
- **Keine Modul-ID.** Die Eingabe enthält keine; Ergebnisse werden über die Position in `items` verknüpft.
  Ändert der Crawler die Reihenfolge, stimmen alte Ergebnisse nicht mehr.

### Technisch (Regelwerk)

- **Regelbasiert, nicht lernend.** Neue Schreibweisen, neue Sondereinheiten oder eine geänderte Struktur führen
  zu Fallback (`low`) oder `unklar`, im ungünstigen Fall zu einer stillen Fehlzuordnung mit `high`.
- **`NODE_RULES` haben Vorrang vor Abschluss-Signalen.** Ein echter Studiengang, dessen Name „Austausch“,
  „Exchange“, „Erasmus“ oder „Schlüsselqualifikation“ enthält, würde als Nicht-Studiengang klassifiziert.
- **`INSTITUTE_RE` und `NOISE_RE` sind Wortsuchen.** Ein Studiengang ohne Abschluss im Namen, dessen Bezeichnung
  „Seminar“, „Institut“, „Pflicht…“ oder „…semester“ enthält, wird übersprungen oder beendet die Suche.
- **Breite Abschluss-Regexe.** `Bachelor…` trifft auch „Bachelorstudiengang“ oder „Bachelorarbeit“, `\bLA\b`
  jedes eigenständige „LA“. Solche Knoten würden fälschlich als Studiengang gelten, wenn sie vor dem eigentlichen
  Studiengang stünden. In den Testdaten kommt das nicht vor.
- **Erste Übereinstimmung gewinnt.** Enthält ein Pfad zwei Studiengänge untereinander (etwa Studiengang und
  darunter eine Vertiefung mit eigenem Abschluss-Wort), wird nur der obere erkannt.
- **Struktur der ersten Ebenen wird vorausgesetzt.** `Root` / Semester / Einheit. Ändert sich das Pfadformat des
  Crawlers, sind Schritt 0 und Schritt 1 anzupassen.
- **Fuzzy-Zusammenführung ist konservativ, aber nicht fehlerfrei.** Sehr ähnliche, aber verschiedene Namen
  innerhalb derselben Fakultät und Abschluss-Kategorie könnten zusammenfallen. In den Testdaten wurde das nicht
  beobachtet. Bei neuen Daten prüfen.
- **Sprache.** Die Regeln sind auf deutsche Bezeichnungen ausgelegt. Englische Muster (`Master's`,
  `Level: Master`) werden nur im Erasmus-/Austausch-Kontext ausgeschlossen, nicht eigens ausgewertet.
- **Speicher/Performance:** unkritisch (Sekundenbereich für ~4000 Pfade); nicht auf Millionen von Pfaden getestet.

### Qualitätssicherung

- Es gibt **keine Referenzdaten** (kein „Goldstandard“ mit von Hand geprüften Zuordnungen) und daher keine
  Kennzahlen wie Genauigkeit oder Trefferquote.
- Die Prüfung bestand darin, die erkannten Bezeichnungen (252 Stück) und die Berichtsabschnitte
  *low / medium / unklar* durchzusehen sowie den Selbsttest mit 12 Fällen laufen zu lassen. Die einzelnen
  ~3000 Zuordnungen wurden **nicht** einzeln kontrolliert.
- Die Regeln wurden **anhand derselben Datei entwickelt**, an der sie getestet wurden. Auf neuen Semestern oder
  Fakultätsstrukturen ist mit schlechteren Ergebnissen zu rechnen (Überanpassung).

---

## Wartung: neue Semester prüfen

1. Extraktor laufen lassen: `python studiengang_extractor.py neue-daten.json --out neu`
2. Im Bericht **`LOW-CONFIDENCE`**, **`MEDIUM`** und **`UNKLAR`** ansehen. Hier zeigen sich Strukturänderungen zuerst.
3. In `neu_studiengaenge.csv` nach auffälligen Namen suchen: leere Klammern, ungewöhnlich lange Namen, Namen
   mit Abschluss-Wörtern mitten im Text, gleiche Fächer mit leicht abweichender Schreibweise.
4. Gefundene Sonderfälle in der Konfiguration ergänzen, Testfall in `_TESTS` hinzufügen, `--selftest` ausführen.
5. Ergebnisse gegen eine Stichprobe von Hand prüfen, insbesondere Lehramt und Wahlfächer.

---

## KI-Disclaimer

**Entstehung.** Der Code (`studiengang_extractor.py`), die Ergebnisdateien und dieses README wurden mit Hilfe
eines KI-Sprachmodells (Claude von Anthropic) in einer Chat-Sitzung am 28.09.2026 erstellt. Grundlage war die
vom Auftraggeber hochgeladene Datei `path-fields.json`. Die Regeln wurden von der KI aus dieser Datei abgeleitet.

**Was das bedeutet:**

- **Keine Gewähr.** Code, Dokumentation und Ergebnisse können Fehler enthalten, auch dort, wo sie plausibel
  aussehen. Eine KI kann Zuordnungen falsch, unvollständig oder inkonsistent liefern und Zusammenhänge
  vermuten, die es nicht gibt. Alles wird „wie besehen“ ohne Zusicherung von Richtigkeit, Vollständigkeit oder
  Eignung für einen bestimmten Zweck bereitgestellt.
- **Menschliche Prüfung ist erforderlich.** Vor jeder Weiterverwendung sind Code und Ergebnisse von einer
  fachkundigen Person zu prüfen, insbesondere Stichproben gegen das Original-Vorlesungsverzeichnis und die
  gültigen Studien- und Prüfungsordnungen.
- **Nur begrenzt getestet.** Es gibt einen kleinen Selbsttest (12 Fälle) und eine Sichtprüfung der erkannten
  Bezeichnungen, aber keine Referenzdaten und keinen Test auf anderen Datenständen (siehe
  [Qualitätssicherung](#qualitätssicherung)).
- **Keine verbindliche Auskunft.** Die Ergebnisse sind **keine** Studienberatung und kein Ersatz für
  Studienordnungen, Modulhandbücher, Prüfungsämter oder die Auskunft der Universität. Sie dürfen nicht als
  alleinige Grundlage für Entscheidungen mit Folgen für Studierende dienen (Studienplanung, Prüfungsanmeldung,
  Anerkennung von Leistungen, Zulassung usw.).
- **Kein offizielles Produkt.** Das Projekt steht in keiner Verbindung zur Universität Leipzig und ist nicht von
  ihr geprüft oder autorisiert. Es besteht ebenfalls keine Verbindung zu Anthropic über die Nutzung des Modells
  hinaus.
- **Datenquelle und Crawling.** Das Crawlen des Vorlesungsverzeichnisses liegt in der Verantwortung des
  Betreibers des Crawlers (Nutzungsbedingungen, `robots.txt`, Last auf dem Server, ggf. Datenschutz und
  Urheberrecht an den Daten). Der Extraktor selbst crawlt nichts.
- **Rechtlicher Status.** Urheberrechtliche Behandlung und Lizenzierung KI-erstellter Inhalte sind je nach
  Rechtsordnung nicht abschließend geklärt. Bei Veröffentlichung oder kommerzieller Nutzung im Zweifel
  rechtlich prüfen lassen und die Kennzeichnungs- und Offenlegungsregeln der eigenen Einrichtung bzw. des
  Publikationsorts zum KI-Einsatz beachten.
- **Verantwortung.** Wer den Code einsetzt oder die Ergebnisse weitergibt, trägt die Verantwortung für die
  Überprüfung und die Art der Verwendung.

Wenn du dieses Projekt weitergibst, behalte diesen Abschnitt bei oder ersetze ihn durch einen eigenen, der die
KI-Beteiligung offenlegt.

---

## Lizenz

Noch nicht festgelegt. Bitte vor Weitergabe oder Veröffentlichung selbst eine Lizenz wählen und hier eintragen
(siehe auch den Hinweis zum rechtlichen Status unter [KI-Disclaimer](#ki-disclaimer)).
