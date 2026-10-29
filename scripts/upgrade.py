"""Additive upgrade, with a BSON backup before touching an existing database."""
import argparse,hashlib,json,sys
from pathlib import Path
from datetime import datetime,timezone
from bson import BSON
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.database import connect,initialize

def backup(database,target):
    target.mkdir(parents=True,exist_ok=False)
    result={'database':database.name,'created_at':datetime.now(timezone.utc).isoformat(),'collections':{}}
    for name in database.list_collection_names():
        output=target/(name+'.bson');count=0
        with output.open('wb') as f:
            for doc in database[name].find({}):f.write(BSON.encode(doc));count+=1
        result['collections'][name]={'count':count,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'indexes':database[name].index_information(),'options':database[name].options()}
    (target/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Preview or back up and apply the stage-two additive schema upgrade.')
    parser.add_argument('--apply',action='store_true');parser.add_argument('--backup-dir',type=Path)
    args=parser.parse_args();client,database=connect()
    try:
        counts={n:database[n].count_documents({}) for n in database.list_collection_names()}
        print(json.dumps({'database':database.name,'before_counts':counts,'mode':'apply' if args.apply else 'preview'},ensure_ascii=False,indent=2))
        if not args.apply:
            print('Preview only. To apply, add --apply --backup-dir <new-private-folder>.')
        else:
            if args.backup_dir is None:raise SystemExit('--backup-dir is required; backups must not be uploaded to GitHub.')
            record=backup(database,args.backup_dir.resolve())
            initialize(database)
            for name in ['users','surveys','responses']:
                assert database[name].count_documents({})==counts.get(name,0),name
            print('Upgrade applied. Legacy collection counts preserved. Backup saved to '+str(args.backup_dir.resolve()))
    finally:client.close()
