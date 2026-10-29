"""Restore a verified backup to a NEW database; never overwrite a live database."""
import argparse,hashlib,json,sys
from pathlib import Path
from bson import decode_file_iter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.database import connect

def restore(client,folder,target_name):
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    if target_name==manifest['database']:raise ValueError('必须恢复到不同名称的新数据库')
    target=client[target_name]
    if target.list_collection_names():raise ValueError('目标数据库非空，拒绝覆盖')
    # Verify every file before writing even the first collection.
    for name,info in manifest['collections'].items():
        if '/' in name or '\\' in name:raise ValueError('非法集合名称')
        path=folder/(name+'.bson')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=info['sha256']:raise ValueError('备份校验失败：'+name)
    for name,info in manifest['collections'].items():
        options={k:v for k,v in info.get('options',{}).items() if k in ['validator','validationLevel','validationAction','collation']}
        collection=target.create_collection(name,**options)
        with (folder/(name+'.bson')).open('rb') as f:
            batch=[]
            for doc in decode_file_iter(f):
                batch.append(doc)
                if len(batch)==500:collection.insert_many(batch);batch=[]
            if batch:collection.insert_many(batch)
        for index_name,index in info.get('indexes',{}).items():
            if index_name=='_id_':continue
            options={k:v for k,v in index.items() if k not in ['key','v','ns']}
            options['name']=index_name
            collection.create_index(index['key'],**options)
        if collection.count_documents({})!=info['count']:raise ValueError('恢复条数不一致：'+name)
    return target

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('backup',type=Path);parser.add_argument('--target-db',required=True);args=parser.parse_args()
    client,_=connect()
    try:
        restored=restore(client,args.backup.resolve(),args.target_db)
        print('Restored to new database: '+restored.name)
    finally:client.close()
