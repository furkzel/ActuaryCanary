"""Compare two run manifests: same run id, inputs, specs, settings and SHA-256 of every output.

Used by the release smoke test: `canary demo` of the built program against
`canary run examples/demo --yes` from source. Standard library only.

    python packaging/compare_manifests.py <manifest.json> <manifest.json>
"""

import json
import sys
from pathlib import Path

COMPARED = ("run_id", "inputs", "specs", "settings")


def differences(a: dict, b: dict) -> list[str]:
    found = [f"{key} differs" for key in COMPARED if a[key] != b[key]]
    first = {o["name"]: o["sha256"] for o in a["outputs"]}
    second = {o["name"]: o["sha256"] for o in b["outputs"]}
    for name in sorted(first.keys() ^ second.keys()):
        found.append(f"output {name} is in only one manifest")
    for name in sorted(first.keys() & second.keys()):
        if first[name] != second[name]:
            found.append(f"output {name} has another SHA-256")
    return found


def main(first: str, second: str) -> int:
    a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in (first, second))
    found = differences(a, b)
    if found:
        print("manifests differ: " + "; ".join(found))
        return 1
    print(f"manifests match: run id {a['run_id']}, SHA-256 equal on {len(a['outputs'])} outputs")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
