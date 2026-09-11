import re
from pathlib import Path


class TestReadme:
    def test_documents_profiles_and_format_2(self):
        readme_path = Path(__file__).resolve().parents[1] / "README.md"
        text = readme_path.read_text()

        assert "Password profiles" in text
        assert "format 2" in text

        start_match = re.search(r"^## Vault profiles$", text, re.MULTILINE)
        assert start_match is not None

        later_starts = [
            m.start()
            for m in re.finditer(r"^## ", text, re.MULTILINE)
            if m.start() > start_match.start()
        ]
        section_end = min(later_starts) if later_starts else len(text)
        section = text[start_match.start() : section_end]

        assert len(section.splitlines()) <= 5

        assert "Choose a group" not in text
        assert "highlighted group" not in text


class TestChangelog:
    def test_unreleased_entry_names_the_group_picker_fix(self):
        path = Path(__file__).resolve().parents[1] / "CHANGELOG.md"

        assert path.is_file()

        text = path.read_text()

        unreleased_match = re.search(r"^## Unreleased", text, re.MULTILINE)
        assert unreleased_match is not None

        heading_starts = [m.start() for m in re.finditer(r"^## ", text, re.MULTILINE)]
        later_starts = [s for s in heading_starts if s > unreleased_match.start()]
        section_end = min(later_starts) if later_starts else len(text)
        section = text[unreleased_match.start() : section_end]

        assert "group picker" in section.lower()
        assert "profile" in section.lower()
        assert len(section.splitlines()) <= 12
