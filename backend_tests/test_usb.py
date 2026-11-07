"""Softcopy files from a USB stick (the kiosk has no way to copy files into a folder, so the operator plugs a stick in)."""
import json
import os

import cv2
import numpy as np
import pytest

import synth
from dicom_utils import write_dicom

import app as backend


def _post(client, url, **body):
    r = client.post(url, data=json.dumps(body), content_type="application/json")
    return r.status_code, r.get_json()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "SAVE_DIR", str(tmp_path / "scans"))
    monkeypatch.setattr(backend, "INBOX_DIR", str(tmp_path / "inbox"))
    os.makedirs(backend.INBOX_DIR)
    backend.app.config["TESTING"] = True
    return backend.app.test_client()


@pytest.fixture()
def stick(tmp_path, monkeypatch):
    """A fake mounted stick called MY_STICK with a few files on it."""
    root = tmp_path / "media" / "raspi" / "MY_STICK"
    os.makedirs(root / "patient42")
    write_dicom(str(root / "patient42" / "IM0001"), (synth.make_digital(300, 220).astype(np.uint16) * 15))  # no extension
    cv2.imwrite(str(root / "scan.png"), synth.make_digital(300, 220))
    (root / "notes.txt").write_text("not an image")
    (root / "report.pdf").write_bytes(b"%PDF-1.4 not an image")
    (root / ".hidden.png").write_bytes(b"x")
    os.makedirs(root / "System Volume Information")
    cv2.imwrite(str(root / "System Volume Information" / "junk.png"), synth.make_digital(100, 80))
    monkeypatch.setattr(backend, "_usb_volumes", lambda mounts_text=None: [{"name": "MY_STICK", "path": str(root)}])
    return root


# ------------------------------------------------------------------------------------ the mount list ----
MOUNTS = r"""/dev/mmcblk0p2 / ext4 rw,noatime 0 0
tmpfs /run tmpfs rw,nosuid 0 0
/dev/mmcblk0p1 /boot/firmware vfat rw 0 0
/dev/sda1 /media/raspi/MY\040STICK vfat rw,nosuid,nodev 0 0
/dev/sdb1 /media/raspi/MY\040STICK vfat rw 0 0
/dev/sdc1 /run/media/sam/DISK exfat rw 0 0
tmpfs /media/raspi/ramdisk tmpfs rw 0 0
/dev/sdd1 /media/raspi/a/b/too/deep ext4 rw 0 0
/dev/sde1 /mnt/other ext4 rw 0 0
"""


def test_only_removable_volumes_below_the_media_folders_are_found():
    vols = backend._usb_volumes(MOUNTS)
    assert [(v["name"], v["path"]) for v in vols] == [
        ("MY STICK", "/media/raspi/MY STICK"),          # \040 in /proc/mounts is a space
        ("MY STICK (2)", "/media/raspi/MY STICK"),      # two sticks with the same name stay distinguishable
        ("DISK", "/run/media/sam/DISK"),
    ]


def test_no_proc_mounts_means_no_sticks(monkeypatch):
    monkeypatch.setattr(backend, "MEDIA_ROOTS", ["/nonexistent-media-folder"])
    assert backend._usb_volumes(MOUNTS) == []


# ----------------------------------------------------------------------------------------- /inbox ----
def test_inbox_without_a_stick_lists_only_the_inbox_folder(client):
    cv2.imwrite(os.path.join(backend.INBOX_DIR, "a.png"), synth.make_digital(300, 220))
    j = client.get("/inbox").get_json()
    assert j["volumes"] == [] and [f["name"] for f in j["files"]] == ["a.png"]
    assert j["files"][0]["source"] == "Inbox" and j["files"][0]["display"] == "a.png"


def test_inbox_lists_the_images_on_the_stick(client, stick):
    j = client.get("/inbox").get_json()
    assert j["volumes"] == ["MY_STICK"]
    by_name = {f["name"]: f for f in j["files"]}
    assert set(by_name) == {"IM0001", "scan.png"}          # no notes, no pdf, no hidden file, no System Volume Information
    f = by_name["IM0001"]
    assert f["format"] == "dicom" and f["source"] == "USB: MY_STICK"
    assert f["path"] == "usb:MY_STICK/" + os.path.join("patient42", "IM0001")
    assert f["display"] == os.path.join("patient42", "IM0001")


def test_inbox_folder_and_stick_are_listed_together(client, stick):
    cv2.imwrite(os.path.join(backend.INBOX_DIR, "local.png"), synth.make_digital(300, 220))
    names = {f["name"] for f in client.get("/inbox").get_json()["files"]}
    assert names == {"IM0001", "scan.png", "local.png"}


def test_health_names_the_sticks(client, stick):
    assert client.get("/health").get_json()["usb_volumes"] == ["MY_STICK"]


# ----------------------------------------------------------------------------------------- /import ----
def test_import_a_dicom_from_the_stick(client, stick):
    code, j = _post(client, "/import", scan_id="U1", side="Left", view="CC",
                    source_path="usb:MY_STICK/" + os.path.join("patient42", "IM0001"))
    assert code == 200 and j["source_format"] == "dicom" and j["converted"] is True
    img = cv2.imread(j["image_path"], cv2.IMREAD_UNCHANGED)
    assert j["image_path"].startswith(backend.SAVE_DIR) and img.dtype == np.uint16   # the PNG is a copy on the device


def test_the_converted_copy_survives_removing_the_stick(client, stick):
    code, j = _post(client, "/import", scan_id="U1", side="Right", view="CC", source_path="usb:MY_STICK/scan.png")
    assert code == 200
    os.remove(stick / "scan.png")
    assert os.path.isfile(j["image_path"])


@pytest.mark.parametrize("bad", [
    "usb:MY_STICK/../../../../etc/passwd",
    "usb:MY_STICK//etc/passwd",
    "usb:MY_STICK/",
    "usb:MY_STICK",
])
def test_import_cannot_leave_the_stick(client, stick, bad):
    assert _post(client, "/import", scan_id="U1", side="Left", view="CC", source_path=bad)[0] == 400


def test_import_refuses_a_symlink_that_points_out_of_the_stick(client, stick, tmp_path):
    secret = tmp_path / "secret.png"
    cv2.imwrite(str(secret), synth.make_digital(100, 80))
    os.symlink(secret, stick / "link.png")
    code, j = _post(client, "/import", scan_id="U1", side="Left", view="CC", source_path="usb:MY_STICK/link.png")
    assert code == 400
    assert "link.png" not in {f["name"] for f in client.get("/inbox").get_json()["files"]}


def test_import_from_a_stick_that_is_gone(client, monkeypatch):
    monkeypatch.setattr(backend, "_usb_volumes", lambda mounts_text=None: [])
    code, j = _post(client, "/import", scan_id="U1", side="Left", view="CC", source_path="usb:MY_STICK/scan.png")
    assert code == 400 and "not connected" in j["error"]


def test_a_file_that_vanished_is_a_404(client, stick):
    code, j = _post(client, "/import", scan_id="U1", side="Left", view="CC", source_path="usb:MY_STICK/nope.png")
    assert code == 404 and "USB stick" in j["error"]
