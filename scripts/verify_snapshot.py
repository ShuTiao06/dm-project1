from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    baseline=json.loads((ROOT/'snapshots/stage1_manifest.json').read_text(encoding='utf-8'))
    failures=[]
    for name,expected in baseline['files'].items():
        path=ROOT/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:failures.append(name)
    archive=ROOT/'snapshots/stage1_baseline.zip'
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=baseline['archive_sha256']:failures.append('snapshot archive')
    if failures:raise SystemExit('与第一阶段基线不同：\n'+'\n'.join(failures))
    print(f"第一阶段快照校验通过：{len(baseline['files'])} files")
