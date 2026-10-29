"""Read-only database diagnostics. Run from project root: python scripts/inspect_db.py."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.database import connect

if __name__=='__main__':
    client,db=connect()
    try:
        result={'database':db.name,'server_version':client.server_info()['version'],'collections':{}}
        for name in ['users','sessions','surveys','responses','question_roots','question_versions','question_shares','question_banks','bank_items']:
            result['collections'][name]={'count':db[name].count_documents({}),'indexes':db[name].index_information()}
        print(json.dumps(result,ensure_ascii=False,indent=2,default=str))
    finally:client.close()
