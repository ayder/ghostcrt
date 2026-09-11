import importlib

import pytest


class TestVaultEditRemoved:
    def test_module_is_gone(self):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("ghostcrt.ui.screens.vault_edit")
