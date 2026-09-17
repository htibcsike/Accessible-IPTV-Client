"""Tests for the release/changelog workflow."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import release


def test_update_changelog_prepends_readable_release_notes(tmp_path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text(
        "# Changelog\n\nExisting release history.\n",
        encoding="utf-8",
    )

    release.update_changelog(
        "1.2.3",
        "## Fixes\n- fix(accessibility): prevent stale focus\n\n## Other\n- docs: update help\n",
        release_date="2026-07-10",
        path=path,
    )

    content = path.read_text(encoding="utf-8")
    assert content.startswith("# Changelog\n\n")
    assert ("## v1.2.3 - 2026-07-10\n\n"
            "### Bug fixes\n\n- Prevent stale focus\n\n"
            "### Other changes\n\n- Update help\n\n") in content
    assert content.index("## v1.2.3") < content.index("Existing release history.")


def test_update_changelog_without_sections_or_notes(tmp_path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text("# Changelog\n\nOld.\n", encoding="utf-8")
    release.update_changelog("1.0.1", "- fix: a\n- fix: a\n", release_date="2026-01-01", path=path)
    release.update_changelog("1.0.2", "", release_date="2026-01-02", path=path)
    content = path.read_text(encoding="utf-8")
    assert "## v1.0.1 - 2026-01-01\n\n- A\n\n" in content
    assert "## v1.0.2 - 2026-01-02\n\n- No notable changes.\n\n" in content


def test_release_notes_group_commits_under_labels():
    commits = [
        {"subject": "feat: record from the player", "body": ""},
        {"subject": "fix(accessibility): announce focus", "body": ""},
        {"subject": "fix: stop crash", "body": ""},
        {"subject": "fix: stop crash", "body": ""},
        {"subject": "docs(i18n): fix Hungarian guide", "body": ""},
        {"subject": "Merge pull request #1", "body": ""},
        {"subject": "Tidy things", "body": ""},
    ]
    assert release.build_release_notes(commits) == (
        "## Features\n- Record from the player\n\n"
        "## Accessibility\n- Announce focus\n\n"
        "## Bug fixes\n- Stop crash\n\n"
        "## Documentation\n- Fix Hungarian guide\n\n"
        "## Other changes\n- Tidy things"
    )
    assert release.determine_bump(commits) == "minor"
    assert release.build_release_notes([]) == "## Other changes\n- No notable changes."


def test_update_changelog_refuses_duplicate_version(tmp_path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text("# Changelog\n\n## v1.2.3 - 2026-07-10\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match=r"already contains v1\.2\.3"):
        release.update_changelog("1.2.3", "- fix: duplicate", path=path)


def test_build_without_the_user_guide_is_refused(tmp_path):
    with pytest.raises(RuntimeError, match=r"help_datas"):
        release.validate_bundled_user_guide(str(tmp_path))
    guide = tmp_path / "_internal" / "docs" / "help" / "en.md"
    guide.parent.mkdir(parents=True)
    guide.write_text("# User Guide {#user-guide}\n", encoding="utf-8")
    release.validate_bundled_user_guide(str(tmp_path))


def test_build_without_the_changelog_is_refused(tmp_path):
    with pytest.raises(RuntimeError, match=r"main\.spec datas"):
        release.validate_bundled_changelog(str(tmp_path))
    changelog = tmp_path / "_internal" / "CHANGELOG.md"
    changelog.parent.mkdir(parents=True)
    changelog.write_text("# Changelog\n", encoding="utf-8")
    release.validate_bundled_changelog(str(tmp_path))


def test_release_commit_stages_changelog(monkeypatch):
    commands = []
    monkeypatch.setattr(release, "run", lambda command, **_kwargs: commands.append(command))

    release.git_commit_and_tag("1.2.3")

    assert commands[0] == ["git", "add", "app_meta.py", "CHANGELOG.md", "locale"]
    assert commands[1] == ["git", "commit", "-m", "chore(release): v1.2.3"]
    assert commands[2] == ["git", "tag", "v1.2.3"]


def test_body_prose_mentioning_a_section_label_is_not_breaking():
    """v2.0.0 regression: a translation commit whose body mentions the
    "Breaking changes" section label was substring-matched and bumped major.
    Classification must read the subject (and a real footer), not body prose.
    """
    commit = {
        "subject": "i18n(hu): finalize v1.136.0 release-note localization",
        "body": (
            "- two recurring-label corrections (Breaking changes, No notable "
            "changes.)\n- refresh What's New introduction\n"
        ),
    }
    assert release.classify_commit(commit) == "Other"
    assert release.determine_bump([commit]) == "patch"


def test_explicit_breaking_markers_still_classify_as_breaking():
    assert release.classify_commit({"subject": "feat!: drop old config", "body": ""}) == "Breaking"
    assert release.classify_commit({"subject": "chore: x", "body": "BREAKING CHANGE: removed key"}) == "Breaking"
    assert release.classify_commit({"subject": "docs: x", "body": "Breaking changes:\n- removed key"}) == "Breaking"
    assert release.determine_bump([{"subject": "fix!: y", "body": ""}]) == "major"


def test_classification_does_not_read_body_prose_for_other_sections():
    docs = {"subject": "i18n(hu): fix catalogues", "body": "keeps the feature wording intact and bug notes out"}
    assert release.classify_commit(docs) == "Other"
    assert release.classify_commit({"subject": "refactor: tidy", "body": "no feature or bug here"}) == "Other"
