from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    manifest=json.loads((ROOT/'snapshots/stage2_manifest.json').read_text(encoding='utf-8'))
    changed=[]
    for name,expected in manifest['files'].items():
        p=ROOT/name
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:changed.append(name)
    if changed:raise SystemExit('Changed or missing files:\n'+'\n'.join(changed))
    print('Stage-two release verified: '+str(len(manifest['files']))+' files')
