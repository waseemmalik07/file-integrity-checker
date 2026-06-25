import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def hash_file(file_path: Path) -> str | None:
    """Return the SHA-256 hash of a file's contents as a hex string.

    Returns None (and logs a warning) if the file can't be read --
    e.g. it was deleted mid-scan, or we don't have permission.
    """
    try:
        content = file_path.read_bytes()
    except (FileNotFoundError, PermissionError) as e:
        logger.warning(f"Skipping unreadable file '{file_path}': {e}")
        return None
    return hashlib.sha256(content).hexdigest()


def scan_folder(folder: Path) -> dict:
    """Walk a folder recursively and return {relative_path: hash} for every file.

    Raises FileNotFoundError if the folder itself doesn't exist or isn't a directory.
    """
    if not folder.exists():
        raise FileNotFoundError(f"Folder '{folder}' does not exist.")
    if not folder.is_dir():
        raise NotADirectoryError(f"'{folder}' is not a directory.")

    hashes = {}
    for file_path in folder.rglob("*"):
        if file_path.is_file():
            rel_path = str(file_path.relative_to(folder))
            file_hash = hash_file(file_path)
            if file_hash is not None:
                hashes[rel_path] = file_hash
    return hashes


def save_baseline(hashes: dict, baseline_file: str = "baseline.json") -> None:
    """Save the hash dictionary to a JSON file."""
    with open(baseline_file, "w") as f:
        json.dump(hashes, f, indent=4)


def load_baseline(baseline_file: str = "baseline.json") -> dict:
    """Load the previously saved hash dictionary from a JSON file.

    Raises FileNotFoundError if the baseline doesn't exist, or
    json.JSONDecodeError if the file exists but contains invalid JSON
    (e.g. it got manually edited and broken, or truncated by a crash).
    """
    path = Path(baseline_file)
    if not path.exists():
        raise FileNotFoundError(f"Baseline file '{baseline_file}' not found.")

    try:
        with open(path, "r") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Baseline file '{baseline_file}' is corrupted: {e}")
        raise


def compare(old_hashes: dict, new_hashes: dict) -> dict:
    """Compare two hash dictionaries and categorize the differences."""
    report = {
        "unchanged": [],
        "modified": [],
        "new": [],
        "missing": [],
    }

    for path, old_hash in old_hashes.items():
        new_hash = new_hashes.get(path)
        if new_hash is None:
            report["missing"].append(path)
        elif new_hash != old_hash:
            report["modified"].append(path)
        else:
            report["unchanged"].append(path)

    for path in new_hashes:
        if path not in old_hashes:
            report["new"].append(path)

    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check files in a folder for unauthorized changes using SHA-256 hashes."
    )
    parser.add_argument(
        "folder",
        type=str,
        help="Path to the folder to scan/monitor.",
    )
    parser.add_argument(
        "--baseline",
        type=str,
        default="baseline.json",
        help="Path to the baseline JSON file (default: baseline.json).",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Overwrite the baseline with the current folder state after reporting.",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    folder = Path(args.folder)

    try:
        if not Path(args.baseline).exists():
            logger.info("No baseline found. Creating one now...")
            hashes = scan_folder(folder)
            save_baseline(hashes, args.baseline)
            logger.info(f"Baseline saved with {len(hashes)} file(s) to '{args.baseline}'.")
            return

        logger.info("Baseline found. Checking for changes...")
        old_hashes = load_baseline(args.baseline)
        new_hashes = scan_folder(folder)
        report = compare(old_hashes, new_hashes)

        logger.info(f"Unchanged: {len(report['unchanged'])}")
        logger.info(f"Modified:  {report['modified']}")
        logger.info(f"New:       {report['new']}")
        logger.info(f"Missing:   {report['missing']}")

        if args.update:
            save_baseline(new_hashes, args.baseline)
            logger.info(f"Baseline updated at '{args.baseline}'.")

    except (FileNotFoundError, NotADirectoryError) as e:
        logger.error(str(e))
        sys.exit(1)
    except json.JSONDecodeError:
        logger.error("Could not parse the baseline file. It may be corrupted. "
                      "Delete it to regenerate a fresh baseline.")
        sys.exit(1)


if __name__ == "__main__":
    main()