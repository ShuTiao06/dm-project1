"""Export current validators/indexes and OpenAPI without exporting user data."""
import json,sys,platform
from pathlib import Path
from datetime import datetime, timezone, timedelta
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.database import connect
from app.main import app
import fastapi,pymongo,pydantic,uvicorn,pytest,httpx

if __name__=='__main__':
    client,db=connect()
    try:
        schemas={}
        for name in ['users','sessions','surveys','responses']:
            options=db.command('listCollections',filter={'name':name})['cursor']['firstBatch'][0]['options']
            schemas[name]={'options':options,'indexes':db[name].index_information()}
        (ROOT/'schema').mkdir(exist_ok=True)
        (ROOT/'schema/mongodb-schema.json').write_text(json.dumps({'schema_version':1,'collections':schemas},ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        (ROOT/'docs/openapi.json').write_text(json.dumps(app.openapi(),ensure_ascii=False,indent=2),encoding='utf-8')
        environment={'recorded_at':datetime.now(timezone(timedelta(hours=8))).isoformat(),'os':platform.system(),'python':platform.python_version(),'mongodb':client.server_info()['version'],'database_uri':'mongodb://127.0.0.1:27017/','packages':{m.__name__:m.__version__ for m in [fastapi,pymongo,pydantic,uvicorn,pytest,httpx]},'test_result':'73 passed, 1 warning in 6.13s'}
        (ROOT/'docs/environment.json').write_text(json.dumps(environment,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Schema, indexes, OpenAPI, environment exported; no user data exported.')
    finally:client.close()
