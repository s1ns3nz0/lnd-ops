"""Owned, atomic Router operation records and a single writer lock (Mac/Linux)."""
import contextlib
import fcntl
import json
import os
import pathlib
import re
import stat
import tempfile


def state_directory():
    return pathlib.Path(os.environ.get("XDG_STATE_HOME", pathlib.Path.home() / ".local/state")) / "lnd-ops/router"


def owned_directory(root):
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    metadata = root.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise ValueError("Router state directory must be owned, private, and not a symlink")


def record_path(root, name):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", name):
        raise ValueError("invalid record name")
    return root / name


def read(root, name):
    path = record_path(root, name)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor) as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077 or metadata.st_nlink != 1:
            raise ValueError("Router record must be an owned private regular file")
        return json.load(stream)


def write(root, name, value):
    owned_directory(root)
    target = record_path(root, name)
    descriptor, temporary = tempfile.mkstemp(prefix=".router-", dir=root)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        directory_fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def operation_lock(root, name="operations.lock"):
    owned_directory(root)
    descriptor = os.open(record_path(root, name), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_nlink != 1 or metadata.st_mode & 0o077:
            raise ValueError("unsafe operation lock")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)
