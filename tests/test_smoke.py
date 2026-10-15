import importlib
import unittest


class PackageImportTest(unittest.TestCase):
    # пакет ядра импортируется
    def test_core_package_imports(self):
        self.assertIsNotNone(importlib.import_module("app.core"))


if __name__ == "__main__":
    unittest.main()
