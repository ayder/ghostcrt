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
    def test_020_entry_names_the_group_picker_fix(self):
        """Keep the 0.2.0 release notes intact as newer releases are added."""
        path = Path(__file__).resolve().parents[1] / "CHANGELOG.md"

        assert path.is_file()

        text = path.read_text()

        entry = re.search(r"^## 0\.2\.0\b.*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
        assert entry is not None
        section = entry.group()

        assert "group picker" in section.lower()
        assert "profile" in section.lower()
        assert len(section.splitlines()) <= 12
