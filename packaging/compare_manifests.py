"""Compare two run manifests: same run id, inputs, specs and output fingerprints.

Used by the release smoke test: `canary demo` of the built program against `canary run` from
source on the same folder. Standard library only.

    python packaging/compare_manifests.py <manifest.json> <manifest.json>
"""

import json
import sys
from pathlib import Path

COMPARED = ("run_id", "inputs", "specs", "settings", "outputs")


def main(first: str, second: str) -> int:
    a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in (first, second))
    differing = [key for key in COMPARED if a[key] != b[key]]
    if differing:
        print(f"manifests differ in: {', '.join(differing)}")
        return 1
    print(f"manifests match: run id {a['run_id']}, {len(a['outputs'])} outputs")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
