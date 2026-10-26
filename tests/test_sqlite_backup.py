"""Focused real CLI stream checks; only temporary synthetic ledgers."""
import json
from pathlib import Path
import subprocess
import sys
import sqlite3
from emby_telegram_bot.deliveries import DeliveryStore

HELPER=Path(__file__).resolve().parents[1]/'scripts/sqlite_volume.py'

def run(action,path,data=None):
    return subprocess.run([sys.executable,str(HELPER),action,str(path)],input=data,capture_output=True)

def ledger(path):
    DeliveryStore(str(path))
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE release_marker (value TEXT)')
        db.execute("INSERT INTO release_marker VALUES ('before')")


def test_dump_restore_preserves_data_and_accepts_quoted_paths(tmp_path):
    source=tmp_path/"source ' test.sqlite3";target=tmp_path/'target.sqlite3'
    ledger(source)
    dumped=run('dump',source)
    assert dumped.returncode==0 and dumped.stdout.startswith(b'SQLite format 3')
    restored=run('restore',target,dumped.stdout)
    assert restored.returncode==0 and json.loads(restored.stdout)['integrity']=='ok'
    with sqlite3.connect(target) as db:assert db.execute('SELECT value FROM release_marker').fetchone()[0]=='before'


def test_bad_restore_leaves_existing_database_intact(tmp_path):
    target=tmp_path/'target.sqlite3';ledger(target)
    result=run('restore',target,b'not a sqlite file')
    assert result.returncode!=0
    with sqlite3.connect(target) as db:assert db.execute('SELECT value FROM release_marker').fetchone()[0]=='before'


def test_dump_missing_source_fails_without_creating_it(tmp_path):
    target=tmp_path/'missing.sqlite3'
    assert run('dump',target).returncode!=0
    assert not target.exists()
