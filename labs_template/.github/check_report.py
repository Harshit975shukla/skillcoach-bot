"""Protected: confirm pytest ran every expected SkillCoach test with no failures, errors or skips."""

import sys
import xml.etree.ElementTree as ElementTree

root = ElementTree.parse(sys.argv[1]).getroot()
suite = root if root.tag == "testsuite" else root.find("testsuite")
counts = {key: int(suite.get(key, "0")) for key in ("tests", "failures", "errors", "skipped")}
expected = {"tests": int(sys.argv[2]), "failures": 0, "errors": 0, "skipped": 0}
if counts != expected:
    sys.exit(f"Expected {expected}, got {counts}")
print(f"All {expected['tests']} SkillCoach checks passed.")
