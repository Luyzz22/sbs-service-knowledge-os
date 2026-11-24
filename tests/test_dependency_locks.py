"""Keep declared dependencies aligned with the hash-locked CI/container inputs."""

import unittest
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]


class DependencyLockTests(unittest.TestCase):
    def test_declared_dependencies_are_present_at_compatible_locked_versions(self):
        for lock_name, manifests in (
            ("requirements.lock", ("requirements.txt",)),
            ("requirements-dev.lock", ("requirements.txt", "requirements-dev.txt")),
        ):
            locked = {}
            for line in (ROOT / lock_name).read_text().splitlines():
                if not line or line[0].isspace() or line.startswith("#"):
                    continue
                requirement = Requirement(line.removesuffix("\\").strip())
                locked[canonicalize_name(requirement.name)] = next(iter(requirement.specifier)).version

            for manifest in manifests:
                for line in (ROOT / manifest).read_text().splitlines():
                    line = line.strip()
                    if not line or line.startswith(("#", "-r ")):
                        continue
                    requirement = Requirement(line)
                    name = canonicalize_name(requirement.name)
                    with self.subTest(lock=lock_name, dependency=name):
                        self.assertIn(name, locked)
                        self.assertIn(locked[name], requirement.specifier)


if __name__ == "__main__":
    unittest.main()
