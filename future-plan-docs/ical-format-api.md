# iCal Export – Fixes & Improvements

> Suggestions for fixing module/course title handling in iCal event summaries, improving the `export_event_parameters` options, and making the output ready for direct calendar import.
> Disclaimer: AI-generated content, may contain inaccuracies. I have reviewed and edited for accuracy, but please verify against the actual codebase and spec.

---

## Problem: Event Title (SUMMARY) with Missing Module/Course Names

The `Event.name` field is often empty because events are just scheduled occurrences — the meaningful title lives on the linked `Course` or `Module`. The current default `ical_title_format="{name}"` produces blank summaries for those events.

### ⚠ M2M Ambiguity

All approaches that try to pick a single course/module from the M2M relationship face the same core problem:

- Events are M2M with courses; ordering is non-deterministic and may change between requests.
- When a user filters by a specific module, they expect *that* module's name in the title — not whichever course happens to be first in the join.
- An event shared across multiple courses/modules has no single "correct" title without knowing the user's context.

The fixes below address this directly.

---

### Fix 4: Use the Active Filter as Title Context

When the user filters events by `module_id`, `module_name`, `course_id`, or `course_name`, use that filter value as the iCal title context instead of guessing from the relationship.

**How it works**: `_build_ical_response()` receives the active filter parameters alongside the items. If `module_name=Datenbanken` was used, inject `_filter_module_name = "Datenbanken"` into every event's placeholder dict. For `module_id` / `course_id`, resolve the name via a single `session.get()` call once before the loop.

The default `ical_title_format` becomes:
```
"{_filter_module_name} – {name}"   (when module filter active)
"{_filter_course_name} – {name}"   (when course filter active)
"{name}"                           (no filter → current behaviour)
```

**Pros**: Always correct — the title matches exactly what the user asked for; no M2M ambiguity; no extra joins per event; no ordering dependency.
**Cons**: Only works when a filter is active; events fetched without a module/course filter still get blank titles.

---

### Fix 6: Require `include=courses` / `include=courses.modules` and Use Stable Ordering

Instead of silently force-loading relations, **require** the user to explicitly include the relations they want in the title, then use a **deterministic sort** (by `id` or `number`) to pick the course/module for placeholders.

**How it works**:
1. If the user requests `?include=courses.modules&format=ical`, the iCal builder has access to the full nested data.
2. Before flattening into placeholders, sort `item["courses"]` by `id` ascending, and each course's `modules` by `id` ascending.
3. Populate `{course_name}`, `{module_name}`, etc. from the first element of the sorted list.
4. If the user didn't include the relation, the placeholder resolves to `""` — making it obvious they need to add `include`.

**Pros**: Deterministic across requests; explicit — the user opts in; no surprise DB queries.
**Cons**: Still "first sorted" rather than "the right one"; requires users to know they need `include`.

---

### Fix 8: User-Provided Event→Module Mapping (`ical_map`)

Let the caller supply an explicit mapping that tells the iCal builder which module (or course) to use for each event's title.

**How it works**: A new JSON query/body parameter `ical_map` accepts an array of `[event_id, module_id]` (or `[event_id, course_id]`) pairs:

```
?format=ical&ical_map_type=module&ical_map=[[42,7],[43,7],[44,12],[45,12]]
```

Or as a JSON body on a POST variant / via a header for GET-friendliness:

```json
{
  "ical_map_type": "module",
  "ical_map": {
    "42": 7,
    "43": 7,
    "44": 12,
    "45": 12
  }
}
```

Before building VEVENTs, the builder loads the referenced module/course names in bulk (one query: `WHERE id IN (...)`), then for each event looks up the mapped ID to set the SUMMARY. Events not present in the map fall back to the default behaviour (`{name}` or the smart fallback).

`ical_map_type` controls what the mapped IDs refer to:
```
?ical_map_type=module   → map values are module IDs (default)
?ical_map_type=course   → map values are course IDs
```

**Pros**: Total precision — the caller decides *exactly* which module/course name each event gets; works for mixed exports with events from different modules; no ordering ambiguity; the frontend can build this map from its own UI state (e.g. the user selected events from a specific module view).
**Cons**: Requires the caller to know the IDs upfront; larger payloads for many events; more complex API surface; GET-unfriendly with large maps (may need POST or header encoding).

---

### Fix 9: Join All Module/Course Names (Concatenation)

Instead of picking one module/course, concatenate **all** linked names into the SUMMARY, separated by a configurable delimiter.

**How it works**: A new parameter controls the join behaviour:

```
?ical_multi_value_separator= / 
```

When building placeholders, if an event has multiple courses or modules:
- `{course_name}` → `"Vorlesung Datenbanken / Übung Datenbanken"`
- `{module_name}` → `"Datenbanken / Informationssysteme"`
- `{staff_names}` → already joined (comma-separated), same treatment

The joined values are sorted by `id` for determinism (same as Fix 6). The default separator is ` / ` but can be set to `, `, ` – `, `\n`, etc.

For the smart fallback, the SUMMARY would be:
```
event.name → joined course names → joined module names → "Event #{id}"
```

So an event linked to modules "Datenbanken" and "Informationssysteme" would get:
```
SUMMARY:Datenbanken / Informationssysteme
```

**Pros**: No information loss — every linked module/course is visible; deterministic (sorted by ID); simple to implement; no caller-side mapping needed; works for mixed exports.
**Cons**: Long titles when events have many links; may be noisy in calendar views; some users may prefer just one name.

---

### Fix 11: `ical_title_per_event` — Inline Per-Event Title via Repeated Query Param

A lightweight alternative to Fix 8's JSON map. The caller passes per-event titles as repeated query parameters keyed by event ID:

```
?format=ical&ical_event_title[42]=Datenbanken VL&ical_event_title[43]=Datenbanken Ü&ical_event_title[44]=Algo VL
```

**How it works**: Parse `ical_event_title[{id}]` params into a `dict[int, str]`. For each event, if a matching entry exists, use it as the literal SUMMARY. Otherwise fall back to the default template. No DB lookups needed — the caller provides the final display string directly.

**Pros**: GET-friendly (no POST body needed); per-event granularity without JSON encoding; the frontend can trivially build these from its UI state; zero ambiguity.
**Cons**: URL length limits with many events (~2000 chars on some clients); repetitive for large exports; the caller must know event IDs and desired titles upfront.

---

### Fix 12: Prefer the Course That Matches the Event's `number` Prefix

Many university systems encode the course number as a prefix of the event number (e.g. event `10-202-2001-2` belongs to course `10-202-2001`). Use this heuristic to pick the "owning" course from the M2M set without requiring user input.

**How it works**: In the iCal builder, for each event:
1. If `event.number` is non-empty, iterate over `item["courses"]` and find the course whose `number` is a prefix of (or equal to) the event's `number`.
2. If exactly one match is found, use that course (and its modules) for placeholders.
3. If zero or multiple matches, fall back to sorted-first (Fix 6) or joined names (Fix 9).

Walk up to the module level the same way: find the module whose `number` is a prefix of the matched course's `number`.

**Pros**: Automatic — no user input needed; exploits existing data conventions; works well when the numbering scheme is consistent; no extra queries.
**Cons**: Relies on a naming convention that may not always hold; brittle if number formats change; university-specific heuristic that may not generalise.

---

### Recommended Approach

**Layered strategy** — combine fixes at different levels so every use case is covered:

| Layer | Fix | What it handles |
|-------|-----|----------------|
| **Default (zero-config)** | Fix 4 | When the user filters by module/course, auto-inject that filter's name as the title context. Covers the most common export scenario correctly with no extra parameters. |
| **Heuristic fallback** | Fix 12 | When no filter is active, prefer the course whose `number` is a prefix of the event's `number` to auto-select the owning course/module. |
| **Fallback for unfiltered exports** | Fix 9 + Fix 6 | When neither filter nor number prefix applies, join all linked module/course names (sorted by `id` for determinism) with a configurable separator. No information loss, no ordering surprises. |
| **Per-event inline override** | Fix 11 | `ical_event_title[id]=...` lets callers set the exact title per event via GET-friendly query params. No JSON encoding required. |
| **Per-event mapping** | Fix 8 | `ical_map` for frontends that know exactly which module each event should display. Maximum correctness for mixed exports. |

**Precedence order** (highest wins):
1. `ical_event_title[id]` (Fix 11) — inline per-event override, GET-friendly; events without an entry fall through
2. `ical_map` (Fix 8) — per-event mapping; events not in the map fall through
3. Filter-derived context (Fix 4) — auto-detected from `module_id`/`course_name`/etc.
4. Number-prefix heuristic (Fix 12) — auto-select owning course/module from `event.number`
5. Joined names fallback (Fix 9 + Fix 6) — concatenate all linked names, sorted by `id`
6. `event.name` → `"Event #{id}"` — last resort

This means: out of the box (no extra params), filtered exports get the correct module name (Fix 4), unfiltered exports try the number-prefix heuristic (Fix 12) then fall back to joining all linked names (Fix 9). Callers who need per-event control use Fix 11 or Fix 8.

---

## Improvements to `export_event_parameters`

### 1. Add `ical_organizer` Parameter

```
ical_organizer: str | None  — e.g. "MAILTO:registrar@uni-leipzig.de"
```

Sets the `ORGANIZER` property on each VEVENT. Calendar apps display this as the event creator. Could also be auto-populated from the first staff member's name if not provided.

### 2. Add `ical_categories` Parameter

```
ical_categories: str | None  — e.g. "{course_type}" or "University,Lecture"
```

Maps to the iCal `CATEGORIES` property. Supports the same `{...}` placeholders. Lets users colour-code events by type in Google Calendar / Outlook.

### 4. Add `ical_filename` Parameter

```
ical_filename: str | None  — default "events.ics"
```

Controls the `Content-Disposition` filename. Useful when exporting filtered subsets (e.g. `informatik-ws2025.ics`).

### 5. Add `ical_calendar_name` Parameter

```
ical_calendar_name: str | None  — e.g. "Uni Leipzig – WS 2025/26"
```

Sets the `X-WR-CALNAME` property on the VCALENDAR. Calendar apps use this as the subscription name when importing or subscribing to the feed.

### 6. Add `ical_timezone` Parameter

```
ical_timezone: str | None  — e.g. "Europe/Berlin" (default)
```

Wraps `dtstart`/`dtend` as timezone-aware datetimes using `VTIMEZONE` or `TZID` parameter. Currently the output uses naive datetimes which calendar apps may interpret in the wrong timezone.

### 8. Replace Individual Format Strings with a Single `ical_template` Preset

Offer named presets that set title/location/description all at once:

```
?ical_template=compact     → summary="{course_name}", no description
?ical_template=detailed    → summary="{module_name} – {course_name}", description="{name}\n{staff_names}"
?ical_template=minimal     → summary="{name}", no description, no location
?ical_template=custom      → use the individual ical_*_format params (default/current)
```

Presets simplify the common case; `custom` preserves full control.

### 9. Add `ical_reminder_minutes` Validation and Multiple Reminders

Currently accepts any integer. Add:
- Validation: `ge=0, le=10080` (max 1 week)
- Accept a **list** instead of single int: `?ical_reminder_minutes=15&ical_reminder_minutes=60` → two VALARM components (one at 15 min, one at 1 hour before)

### 12. Add `ical_color` Parameter

```
ical_color: str | None  — e.g. "#3B82F6" or "tomato"
```

Sets the non-standard but widely supported `COLOR` property (RFC 7986) on each VEVENT. Apple Calendar, Thunderbird, and some Google Calendar clients use this to tint events. Supports `{...}` placeholders so users could theoretically map `{course_type}` to a colour via a lookup, but a static hex value is the primary use case.
Maybe support a color palette parameter that maps course types to colours?

### 13. Add `ical_busy_status` Parameter

```
ical_busy_status: str | None  — enum: BUSY | FREE | BUSY-TENTATIVE | BUSY-UNAVAILABLE
```

Sets the `TRANSP` property (`OPAQUE` for busy, `TRANSPARENT` for free). Outlook and Google Calendar use this to determine free/busy visibility. Default could be `BUSY` (OPAQUE) since university events typically block the time slot. Distinct from `ical_status` (CONFIRMED/CANCELLED), which indicates event certainty rather than availability.

### 15. Add `ical_recurrence` Collapse Parameter

```
ical_collapse_recurring: bool = False
```

When `True`, detect events with the same course, time slot, and location repeating on the same weekday across consecutive weeks, and collapse them into a single VEVENT with an `RRULE` (e.g. `FREQ=WEEKLY;COUNT=14`) plus `EXDATE` entries for skipped weeks. This dramatically reduces file size for semester-long feeds and is the native iCal way to represent repeating lectures. When `False` (default), each occurrence stays a separate VEVENT as today.
