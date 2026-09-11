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
