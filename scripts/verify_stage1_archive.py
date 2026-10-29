"""Verify the archived stage-one ZIP itself, not the now-evolved working tree."""
from pathlib import Path
import hashlib,json,zipfile
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    manifest=json.loads((ROOT/'snapshots/stage1_manifest.json').read_text(encoding='utf-8'))
    archive=ROOT/'snapshots/stage1_baseline.zip'
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==manifest['archive_sha256'],'archive hash mismatch'
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for name,expected in manifest['files'].items():assert hashlib.sha256(z.read(name)).hexdigest()==expected,name
    print('Stage-one archived baseline verified. Current stage-two changes are expected.')
