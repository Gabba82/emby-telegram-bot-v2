"""SQLite backup stream helper; runs locally for check or in an isolated container."""
import json
from contextlib import closing
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path


def open_readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=10)


def verify(connection):
    result = connection.execute('PRAGMA integrity_check').fetchall()
    if result != [('ok',)]:
        raise ValueError('SQLite integrity_check failed')
    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'operations', 'deliveries', 'attempts'} <= tables:
        raise ValueError('Not a publication history database')
    return connection.execute('SELECT count(*) FROM deliveries').fetchone()[0]


def main():
    action, path = sys.argv[1:]
    if action == 'check':
        with closing(open_readonly(path)) as connection:
            print(json.dumps(dict(integrity='ok', deliveries=verify(connection))))
        return
    with tempfile.TemporaryDirectory(prefix='emby-sqlite-') as directory:
        temporary = Path(directory) / 'history.sqlite3'
        if action == 'dump':
            with closing(open_readonly(path)) as source, closing(sqlite3.connect(temporary)) as target:
                source.backup(target)
                verify(target)
            with temporary.open('rb') as stream:
                shutil.copyfileobj(stream, sys.stdout.buffer)
        elif action == 'restore':
            with temporary.open('wb') as stream:
                shutil.copyfileobj(sys.stdin.buffer, stream)
            with closing(open_readonly(temporary)) as source:
                verify(source)  # Validate BEFORE opening the destination for writing.
                with closing(sqlite3.connect(path, timeout=10)) as target:
                    source.backup(target)
                    print(json.dumps(dict(integrity='ok', deliveries=verify(target))))
        else:
            raise ValueError('Action must be check, dump or restore')


if __name__ == '__main__':
    main()
