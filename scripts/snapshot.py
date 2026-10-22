"""Freeze stage-one source and design; refuses to replace an existing baseline."""
from pathlib import Path
import hashlib,json,zipfile
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    target=ROOT/'snapshots';target.mkdir(exist_ok=True)
    manifest=target/'stage1_manifest.json';archive=target/'stage1_baseline.zip'
    if manifest.exists() or archive.exists():raise SystemExit('第一阶段快照已存在，不覆盖历史基线。')
    files=[]
    for path in sorted(ROOT.rglob('*')):
        rel=path.relative_to(ROOT)
        if path.is_file() and not any(x in rel.parts for x in ['__pycache__','.pytest_cache','.git','snapshots']) and path.name!='.env':files.append(path)
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files:z.write(p,p.relative_to(ROOT).as_posix())
    manifest.write_text(json.dumps({'stage':1,'schema_version':1,'created_at':datetime.now(timezone.utc).isoformat(),'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':hashes},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'第一阶段快照已保存：{len(files)} files')
