import json

import download


def _write_dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "DATA_DIR", tmp_path)
    monkeypatch.setattr(download, "MARKER", tmp_path / ".download_complete")
    for name, key in download.REQUIRED_FILES.items():
        (tmp_path / name).write_text(json.dumps({key: "x"}) + "\n")


def test_missing_dataset_is_invalid(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "DATA_DIR", tmp_path)
    monkeypatch.setattr(download, "MARKER", tmp_path / ".download_complete")
    assert not download.dataset_is_valid()


def test_files_without_marker_are_invalid(tmp_path, monkeypatch):
    _write_dataset(tmp_path, monkeypatch)
    assert not download.dataset_is_valid()


def test_complete_dataset_is_valid(tmp_path, monkeypatch):
    _write_dataset(tmp_path, monkeypatch)
    download.MARKER.touch()
    assert download.dataset_is_valid()


def test_corrupt_or_empty_file_is_invalid(tmp_path, monkeypatch):
    _write_dataset(tmp_path, monkeypatch)
    download.MARKER.touch()
    review = tmp_path / "yelp_academic_dataset_review.json"
    review.write_text("garbage\n")
    assert not download.dataset_is_valid()
    review.write_text("")
    assert not download.dataset_is_valid()
