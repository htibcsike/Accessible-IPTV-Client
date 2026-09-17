"""Localized display of release notes (Help > What's New and the update prompt).

Release notes are written in English by ``tools/release.py``. Two kinds of text
in them are translated, from two different catalogues:

- Section labels ("Features", "Bug fixes", ...) recur in every release, so they
  are ordinary application strings in the ``iptvclient`` domain.
- Individual bullets come from the ``release_notes`` domain
  (:data:`i18n.NOTES_DOMAIN`). ``tools/i18n_tools.py`` fills its template from
  the newest :data:`RELEASE_WINDOW` releases in ``CHANGELOG.md`` only, so
  bullets of older releases retire from the catalogues and stay English.

That domain is exempt from the "every shipped catalogue is fully translated"
rule: translators fill it in after a release, and until they do each bullet
falls back to its English text.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

import i18n
from i18n import N_, gettext as _

# The current release plus the previous two (agreed on issue #25).
RELEASE_WINDOW = 3

# (stable section key, English display label), in release-notes order. The key
# is what tools/release.py classifies commits into and bumps versions from.
SECTIONS = (
    ("Breaking", N_("Breaking changes")),
    ("Features", N_("Features")),
    ("Accessibility", N_("Accessibility")),
    ("Fixes", N_("Bug fixes")),
    ("Documentation", N_("Documentation")),
    ("Other", N_("Other changes")),
)
SECTION_KEYS = tuple(section[0] for section in SECTIONS)
NO_NOTABLE_CHANGES = N_("No notable changes.")

# Labels by lowercase heading text; the bare keys are what release bodies
# published before v1.135.5 used ("## Fixes", "## Other").
_LABELS = {}
for _key, _label in SECTIONS:
    _LABELS[_key.lower()] = _label
    _LABELS[_label.lower()] = _label

_CONVENTIONAL_PREFIX = re.compile(
    r"^(?:feat|fix|perf|docs|test|chore|build|ci|refactor|style|a11y)(?:\([^)]+\))?!?:\s*",
    re.I,
)
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_VERSION_HEADING = re.compile(r"^#{1,6}\s+v\d+\.\d+", re.I)


def section_label(heading: str) -> Optional[str]:
    """English label for a section heading's text, or None if it is not one."""
    return _LABELS.get((heading or "").strip().lower())


def clean_item(text: str) -> str:
    """Turn a conventional-commit subject into a readable release-note bullet."""
    item = _CONVENTIONAL_PREFIX.sub("", (text or "").strip())
    if not item:
        return ""
    return item[0].upper() + item[1:]


def parse_sections(notes: str) -> List[Tuple[Optional[str], List[str]]]:
    """Split release notes into ``[(label or None, [bullet, ...]), ...]``.

    Bullets are cleaned and de-duplicated across the whole release; sections
    that end up empty are dropped.
    """
    sections: List[Tuple[Optional[str], List[str]]] = []
    current: List[str] = []
    seen = set()
    label: Optional[str] = None
    started = False
    for raw in (notes or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = _HEADING.match(line)
        if heading:
            if started and current:
                sections.append((label, current))
            label, current, started = section_label(heading.group(2)), [], True
            continue
        started = True
        if line.startswith(("- ", "* ")):
            line = line[2:].strip()
        item = clean_item(line)
        if item and item.lower() not in seen:
            seen.add(item.lower())
            current.append(item)
    if current:
        sections.append((label, current))
    return sections


def translate_note(text: str) -> str:
    """Translate one release-note bullet, falling back to the English text."""
    if text == NO_NOTABLE_CHANGES:
        return _(text)
    return i18n.notes_gettext(text)


def localize_notes(text: str, clean: bool = False) -> str:
    """Translate the section labels and bullets of a release-notes body.

    Version headings, blank lines and anything unrecognised pass through
    unchanged. ``clean`` strips conventional-commit prefixes from bullets first,
    for release bodies published before bullets were written clean.
    """
    out = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        heading = _HEADING.match(stripped)
        if heading and not _VERSION_HEADING.match(stripped):
            label = section_label(heading.group(2))
            if label:
                out.append(f"{heading.group(1)} {_(label)}")
                continue
        if stripped.startswith(("- ", "* ")):
            item = stripped[2:].strip()
            if clean:
                item = clean_item(item) or item
            out.append(f"- {translate_note(item)}")
            continue
        out.append(line)
    return "\n".join(out)


def localize_changelog(text: str, app_name: str) -> str:
    """The bundled ``CHANGELOG.md`` as shown in Help > What's New.

    The maintainer-facing preamble (everything before the first version
    heading) is replaced by a translated introduction.
    """
    lines = (text or "").splitlines()
    first = next((i for i, line in enumerate(lines) if _VERSION_HEADING.match(line.strip())),
                 len(lines))
    intro = [
        "# " + _("What's New"),
        "",
        _("Changes in each version of {app}, newest first. Notes for the latest "
          "versions appear in your language once they have been translated; "
          "older entries stay in English.").format(app=app_name),
        "",
        "",
    ]
    return "\n".join(intro) + localize_notes("\n".join(lines[first:])) + "\n"
