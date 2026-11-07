"""Validate the Yelp dataset and download it from Kaggle only if it is missing or incomplete."""

import json
import os
import sys
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "/data/raw"))
KAGGLE_DATASET = os.getenv("KAGGLE_DATASET", "yelp-dataset/yelp-dataset")
MARKER = DATA_DIR / ".download_complete"

# file name -> key that every record must have
REQUIRED_FILES = {
    "yelp_academic_dataset_business.json": "business_id",
    "yelp_academic_dataset_review.json": "review_id",
}


def file_is_valid(path: Path, key: str) -> bool:
    """The file exists, is not empty and its first line is a JSON object with `key`."""
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return False
        with path.open(encoding="utf-8") as f:
            return key in json.loads(f.readline())
    except (OSError, ValueError, TypeError):
        return False


def dataset_is_valid() -> bool:
    # The marker tells a finished download from one interrupted half-way.
    return MARKER.exists() and all(file_is_valid(DATA_DIR / name, key) for name, key in REQUIRED_FILES.items())


def has_credentials() -> bool:
    return bool(
        os.getenv("KAGGLE_API_TOKEN")
        or (os.getenv("KAGGLE_USERNAME") and os.getenv("KAGGLE_KEY"))
        or Path.home().joinpath(".kaggle", "kaggle.json").exists()
        or Path.home().joinpath(".kaggle", "access_token").exists()
    )


def download() -> None:
    import kagglehub

    MARKER.unlink(missing_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_FILES:
        print(f"Downloading {name} from {KAGGLE_DATASET}...", flush=True)
        kagglehub.dataset_download(KAGGLE_DATASET, path=name, output_dir=str(DATA_DIR), force_download=True)


def main() -> int:
    if dataset_is_valid():
        print(f"Dataset already present and valid in {DATA_DIR}")
        return 0

    print(f"Dataset missing or incomplete in {DATA_DIR}")
    if not has_credentials():
        if "--if-credentials" in sys.argv:
            print("No Kaggle credentials: skipping, `dataset` will download it when it starts.")
            return 0
        print(
            "ERROR: Kaggle credentials not found. Set KAGGLE_API_TOKEN, or KAGGLE_USERNAME and "
            "KAGGLE_KEY (shell or .env), or place the files in the data volume.",
            file=sys.stderr,
        )
        return 1

    download()

    invalid = [n for n, k in REQUIRED_FILES.items() if not file_is_valid(DATA_DIR / n, k)]
    if invalid:
        print(f"ERROR: downloaded files are invalid: {', '.join(invalid)}", file=sys.stderr)
        return 1

    MARKER.touch()
    print("Dataset downloaded and validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
