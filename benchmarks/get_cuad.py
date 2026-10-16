"""Downloads CUAD v1 (CC BY 4.0, The Atticus Project) into data/cuad and writes the fixed
50-contract subset the audit benchmark uses. The subset is written once and committed.

Run: python -m benchmarks.get_cuad
"""

import argparse
from pathlib import Path

from auditor.bench.cuad import download_cuad, load_cuad, save_subset, select_subset

SUBSET_FILE = Path(__file__).parent / "subset.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="get_cuad")
    parser.add_argument("--dest", default="data/cuad")
    parser.add_argument("--subset-size", type=int, default=50)
    args = parser.parse_args(argv)
    path = download_cuad(args.dest)
    print(f"CUAD ready: {path}")
    if SUBSET_FILE.exists():
        print(f"subset kept: {SUBSET_FILE}")
        return 0
    contracts, _ = load_cuad(path)
    save_subset(SUBSET_FILE, select_subset(contracts, args.subset_size))
    print(f"subset written: {SUBSET_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
