"""Tests for localized release notes (issue #25): Help > What's New and the update prompt."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import i18n  # noqa: E402
import release_notes  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import i18n_tools  # noqa: E402

CHANGELOG = """# Changelog

Maintainer preamble.
## v1.0.4 - 2026-01-04

### Bug fixes

- Newest fix

## v1.0.3 - 2026-01-03

- Shared note
- No notable changes.

## v1.0.2 - 2026-01-02

- Shared note
- Middle note

## v1.0.1 - 2026-01-01

- Retired note
"""


def teardown_function(_func):
    i18n.set_language("en")


def _write_catalogue(locale_root, code, domain, translations):
    po = locale_root / code / "LC_MESSAGES" / f"{domain}.po"
    po.parent.mkdir(parents=True, exist_ok=True)
    body = 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n\n'
    for msgid, msgstr in translations.items():
        body += f'msgid "{msgid}"\nmsgstr "{msgstr}"\n\n'
    po.write_text(body, encoding="utf-8")
    i18n_tools.compile_po(str(po))


def _activate(monkeypatch, tmp_path, code, notes, labels):
    root = tmp_path / "locale"
    _write_catalogue(root, code, i18n.NOTES_DOMAIN, notes)
    _write_catalogue(root, code, i18n.DOMAIN, labels)
    monkeypatch.setattr(i18n, "locale_dir", lambda: str(root))
    i18n.set_language(code)


def test_window_matches_between_runtime_and_tooling():
    assert i18n_tools.NOTES_WINDOW == release_notes.RELEASE_WINDOW == 3
    assert i18n_tools.NOTES_DOMAIN == i18n.NOTES_DOMAIN
    assert i18n_tools.NO_NOTABLE_CHANGES == release_notes.NO_NOTABLE_CHANGES


def test_extraction_keeps_only_the_newest_three_releases(tmp_path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text(CHANGELOG, encoding="utf-8")
    messages = i18n_tools.extract_release_notes(str(path))
    # Section labels and "No notable changes." belong to the iptvclient domain.
    assert set(messages) == {"Newest fix", "Shared note", "Middle note"}
    assert len(messages["Shared note"]["locations"]) == 2


def test_update_retires_old_notes_and_keeps_translations(tmp_path, monkeypatch):
    locale_root = tmp_path / "locale"
    main_po = locale_root / "hu" / "LC_MESSAGES" / "iptvclient.po"
    main_po.parent.mkdir(parents=True)
    main_po.write_text('msgid ""\nmsgstr ""\n"Language: hu\\n"\n', encoding="utf-8")
    notes_po = main_po.parent / "release_notes.po"
    notes_po.write_text(
        'msgid ""\nmsgstr ""\n"Language: hu\\n"\n\n'
        'msgid "Shared note"\nmsgstr "Közös jegyzet"\n\n'
        'msgid "Retired note"\nmsgstr "Régi jegyzet"\n',
        encoding="utf-8",
    )
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG, encoding="utf-8")
    monkeypatch.setattr(i18n_tools, "LOCALE_DIR", str(locale_root))
    monkeypatch.setattr(i18n_tools, "NOTES_POT_PATH", str(locale_root / "release_notes.pot"))

    i18n_tools.cmd_notes(str(changelog))

    entries = {e["msgid"]: e.get("msgstr", "") for e in i18n_tools.parse_po(str(notes_po))}
    assert entries[""].startswith("Language: hu")
    assert entries["Shared note"] == "Közös jegyzet"
    assert entries["Newest fix"] == ""
    assert "Retired note" not in entries
    assert (locale_root / "release_notes.pot").exists()


def test_new_language_gets_a_seeded_notes_catalogue(tmp_path, monkeypatch):
    locale_root = tmp_path / "locale"
    main_po = locale_root / "de" / "LC_MESSAGES" / "iptvclient.po"
    main_po.parent.mkdir(parents=True)
    main_po.write_text('msgid ""\nmsgstr ""\n"Language: de\\n"\n', encoding="utf-8")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG, encoding="utf-8")
    monkeypatch.setattr(i18n_tools, "LOCALE_DIR", str(locale_root))
    monkeypatch.setattr(i18n_tools, "NOTES_POT_PATH", str(locale_root / "release_notes.pot"))

    i18n_tools.cmd_notes(str(changelog))
    i18n_tools.cmd_notes(str(changelog))  # idempotent

    text = (main_po.parent / "release_notes.po").read_text(encoding="utf-8")
    assert text.count('"Language: de\\n"') == 1
    assert text.count('msgid "Newest fix"') == 1
    # The main-domain update never touches the notes catalogue.
    assert i18n_tools.find_po_files(i18n_tools.DOMAIN) == [str(main_po)]


def test_committed_notes_catalogues_cover_the_current_window():
    expected = set(i18n_tools.extract_release_notes())
    assert expected, "CHANGELOG.md has no release notes to translate"
    for code in i18n.SHIPPED_CATALOGS:
        po = os.path.join(REPO, "locale", code, "LC_MESSAGES", "release_notes.po")
        msgids = {e["msgid"] for e in i18n_tools.parse_po(po) if e.get("msgid")}
        # Untranslated entries are allowed: they fall back to English.
        assert msgids == expected, code
        assert os.path.exists(os.path.splitext(po)[0] + ".mo"), code


def test_untranslated_notes_fall_back_to_english(tmp_path, monkeypatch):
    _activate(monkeypatch, tmp_path, "hu",
              notes={"Newest fix": "Legújabb javítás"},
              labels={"Bug fixes": "Hibajavítások", "Other changes": "Egyéb változások",
                      "No notable changes.": "Nincs említésre méltó változás."})
    shown = release_notes.localize_notes(
        "## v1.0.4 - 2026-01-04\n\n### Bug fixes\n\n- Newest fix\n- Middle note\n"
        "## Other\n- No notable changes.\n### Custom heading"
    )
    assert shown.splitlines() == [
        "## v1.0.4 - 2026-01-04",
        "",
        "### Hibajavítások",
        "",
        "- Legújabb javítás",
        "- Middle note",
        "## Egyéb változások",
        "- Nincs említésre méltó változás.",
        "### Custom heading",
    ]


def test_update_prompt_cleans_legacy_release_bodies(tmp_path, monkeypatch):
    _activate(monkeypatch, tmp_path, "hu",
              notes={"Restore show-player shortcut": "Lejátszó megjelenítése billentyű visszaállítva"},
              labels={"Bug fixes": "Hibajavítások"})
    shown = release_notes.localize_notes(
        "## Fixes\n- fix(accessibility): restore show-player shortcut", clean=True)
    assert shown == "## Hibajavítások\n- Lejátszó megjelenítése billentyű visszaállítva"


def test_changelog_preamble_is_replaced_by_a_translated_intro():
    shown = release_notes.localize_changelog(CHANGELOG, "Accessible IPTV Client")
    assert shown.startswith("# What's New\n\nChanges in each version of Accessible IPTV Client")
    assert "older entries stay in English.\n\n## v1.0.4" in shown
    assert "Maintainer preamble" not in shown
    assert "## v1.0.4 - 2026-01-04\n\n### Bug fixes\n\n- Newest fix" in shown
    assert shown.rstrip().endswith("- Retired note")


def test_parse_sections_dedupes_and_maps_legacy_headings():
    assert release_notes.parse_sections(
        "## Fixes\n- fix: a\n- fix: A\n## Weird\n- b\n## Other\n"
    ) == [("Bug fixes", ["A"]), (None, ["B"])]
