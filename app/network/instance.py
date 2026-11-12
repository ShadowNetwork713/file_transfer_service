import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class DataDirectoryInUseError(Exception):
    pass


@contextmanager
def lock_data_directory(data_dir: str | Path) -> Iterator[Path]:
    path = Path(data_dir).expanduser()
    if path.exists() and not path.is_dir():
        raise ValueError(f"Путь данных не является каталогом: {path}")

    path.mkdir(parents=True, exist_ok=True)
    resolved_path = path.resolve()
    lock_file = (resolved_path / ".node.lock").open("a+b")
    locked = False
    try:
        try:
            if os.name == "nt":
                import msvcrt

                lock_file.seek(0, os.SEEK_END)
                if lock_file.tell() == 0:
                    lock_file.write(b"1")
                    lock_file.flush()
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as error:
            raise DataDirectoryInUseError(
                f"Каталог данных уже используется другой нодой: {resolved_path}"
            ) from error

        yield resolved_path
    finally:
        if locked:
            if os.name == "nt":
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()
