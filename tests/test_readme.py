import re
from pathlib import Path


class TestReadme:
    def test_documents_profiles_and_format_2(self):
        readme_path = Path(__file__).resolve().parents[1] / "README.md"
        text = readme_path.read_text()

        assert "## Vault profiles" in text
        assert "Create / update profile…" in text
        assert "Assign profile to selected host…" in text
        assert "format 2" in text
        assert "Multi-alias vault entries are per selected alias" in text

        assert text.index("## Groups") < text.index("## Vault profiles")
        assert text.index("## Vault profiles") < text.index("## Security notes")

    def test_documents_group_picker(self):
        readme_path = Path(__file__).resolve().parents[1] / "README.md"
        text = readme_path.read_text()

        assert "highlighted group" in text
        assert "Cancel discards" in text

        groups_match = re.search(r"^## Groups$", text, re.MULTILINE)
        vault_match = re.search(r"^## Vault profiles$", text, re.MULTILINE)
        assert groups_match is not None
        assert vault_match is not None

        groups_section = text[groups_match.start() : vault_match.start()]

        assert "highlighted group" in groups_section
        assert "Cancel discards" in groups_section
