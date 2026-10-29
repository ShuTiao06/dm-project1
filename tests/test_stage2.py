"""Actual MongoDB integration tests for incremental stage-two behavior."""
import os,uuid,copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from bson import ObjectId
from pymongo import MongoClient
from pymongo.errors import WriteError
from fastapi.testclient import TestClient
import pytest
from app.main import app
from app.database import initialize

@pytest.fixture(scope='module')
def clients():
    name='dm_project1_stage2_test_'+uuid.uuid4().hex
    old=os.environ.get('MONGODB_DB');os.environ['MONGODB_DB']=name
    a=TestClient(app);b=TestClient(app);outsider=TestClient(app)
    try:
        with a:
            for client in [a,b,outsider]:
                body={'username':'u_'+uuid.uuid4().hex[:15],'password':'StageTwoTest123!'}
                assert client.post('/api/auth/register',json=body).status_code==201
                assert client.post('/api/auth/login',json=body).status_code==200
            yield a,b,outsider
    finally:
        c=MongoClient(os.getenv('MONGODB_URI','mongodb://127.0.0.1:27017/'),serverSelectionTimeoutMS=3000)
        assert name.startswith('dm_project1_stage2_test_') and len(name)==56
        c.drop_database(name);c.close();b.close();outsider.close()
        if old is None:os.environ.pop('MONGODB_DB',None)
        else:os.environ['MONGODB_DB']=old

def definition(kind='number',**changes):
    return {'title':'年龄','type':kind,'required':True,'options':['A','B','C'] if kind in ('single','multiple') else [],'validation':{'integer':True,'min_value':0,'max_value':120} if kind=='number' else {},**changes}

def create(a,d=None):
    r=a.post('/api/library/questions',json={'definition':d or definition(),'note':'初始版本'})
    assert r.status_code==201,r.text
    return r.json()

def version(a,root,parent,d=None):
    r=a.post('/api/library/questions/'+root+'/versions',json={'parent_version_id':parent,'definition':d or definition(title='年龄（新版本）'),'note':'更新'})
    assert r.status_code==201,r.text
    return r.json()

def survey(a,vid,local='age',multiple=True):
    s=a.post('/api/surveys',json={'title':'复用调查','allow_multiple':multiple}).json()
    r=a.post('/api/surveys/'+s['id']+'/import-question?revision=1',json={'version_id':vid,'local_id':local})
    assert r.status_code==201,r.text
    s=r.json();assert a.post('/api/surveys/'+s['id']+'/publish').status_code==200
    return s

def submit(a,sid,value,key='age'):
    r=a.post('/api/public/surveys/'+sid+'/responses',json={'answers':{key:value},'anonymous':True,'request_id':uuid.uuid4().hex})
    assert r.status_code==201,r.text
    return r.json()

def share(a,b,rid):
    username=b.get('/api/auth/me').json()['username']
    r=a.post('/api/library/questions/'+rid+'/shares',json={'username':username})
    assert r.status_code==201,r.text

def payload(s):return {k:s[k] for k in ['title','description','allow_anonymous','allow_multiple','deadline','questions']}

def test_create_read_immutable_versions(clients):
    a,b,c=clients;x=create(a);rid=x['root']['id'];v=x['version']
    assert v['number']==1 and v['parent_version_id'] is None and len(v['fingerprint'])==64
    assert b.get('/api/library/questions/'+rid).status_code==404
    assert a.patch('/api/library/questions/'+rid+'/versions/'+v['id'],json={'title':'篡改'}).status_code==404
    assert a.get('/api/library/questions/'+rid).json()['versions'][0]==v

def test_versions_branch_restore_and_coexist(clients):
    a,_,_=clients;x=create(a);rid=x['root']['id'];v1=x['version']
    v2=version(a,rid,v1['id']);v3=version(a,rid,v1['id'],definition(title='另一分支'))
    assert [v2['number'],v3['number']]==[2,3]
    assert v2['parent_version_id']==v3['parent_version_id']==v1['id']
    restored=a.post(f'/api/library/questions/{rid}/versions/{v1["id"]}/restore').json()
    assert restored['number']==4 and restored['restored_from_version_id']==v1['id']
    assert restored['definition']==v1['definition'] and restored['fingerprint']==v1['fingerprint']
    assert len(a.get('/api/library/questions/'+rid).json()['versions'])==4

def test_published_snapshot_never_changes(clients):
    a,_,_=clients;x=create(a);rid=x['root']['id'];v1=x['version'];s=survey(a,v1['id']);submit(a,s['id'],18)
    before=a.get('/api/surveys/'+s['id']).json()
    v2=version(a,rid,v1['id'],definition(title='年龄（岁）',validation={'max_value':60,'integer':True}))
    after=a.get('/api/surveys/'+s['id']).json()
    assert before==after and after['questions'][0]['source']['version_id']==v1['id']
    s2=survey(a,v2['id']);assert s2['questions'][0]['title']=='年龄（岁）'
    assert a.get('/api/surveys/'+s['id']+'/stats').json()['questions'][0]['average']==18

def test_sharing_use_not_edit_and_revoke(clients):
    a,b,c=clients;x=create(a);rid=x['root']['id'];v=x['version'];share(a,b,rid)
    assert b.get('/api/library/questions/'+rid).status_code==200
    assert rid in [r['id'] for r in b.get('/api/library/questions?scope=shared').json()]
    assert rid in [r['id'] for r in a.get('/api/library/questions?scope=owned').json()]
    assert c.get('/api/library/questions/'+rid).status_code==404
    assert b.post('/api/library/questions/'+rid+'/versions',json={'definition':definition(),'parent_version_id':v['id']}).status_code==404
    s=survey(b,v['id']);uid=b.get('/api/auth/me').json()['id']
    assert a.delete('/api/library/questions/'+rid+'/shares/'+uid).status_code==200
    assert b.get('/api/library/questions/'+rid).status_code==404
    assert b.post('/api/surveys',json={'title':'伪造','questions':s['questions']}).status_code==404
    submit(b,s['id'],22)
    assert b.get('/api/surveys/'+s['id']+'/stats').json()['total_responses']==1

def test_revoked_existing_draft_can_save_but_not_duplicate_source(clients):
    a,b,_=clients;x=create(a);rid=x['root']['id'];share(a,b,rid)
    s=b.post('/api/surveys',json={'title':'草稿'}).json()
    s=b.post('/api/surveys/'+s['id']+'/import-question?revision=1',json={'version_id':x['version']['id'],'local_id':'age'}).json()
    uid=b.get('/api/auth/me').json()['id'];a.delete('/api/library/questions/'+rid+'/shares/'+uid)
    body=payload(s);body['description']='仍能编辑说明'
    r=b.put('/api/surveys/'+s['id']+'?revision=2',json=body);assert r.status_code==200
    body['questions'].append({**body['questions'][0],'id':'age2'})
    assert b.put('/api/surveys/'+s['id']+'?revision=3',json=body).status_code==404

def test_forged_source_and_changed_content_rejected(clients):
    a,_,_=clients;x=create(a);s=a.post('/api/surveys',json={'title':'draft'}).json()
    s=a.post('/api/surveys/'+s['id']+'/import-question?revision=1',json={'version_id':x['version']['id'],'local_id':'age'}).json()
    body=payload(s);body['questions'][0]['title']='改坏'
    assert a.put('/api/surveys/'+s['id']+'?revision=2',json=body).status_code==422
    body=payload(s);body['questions'][0]['source']['fingerprint']='0'*64
    assert a.post('/api/surveys',json=body).status_code==422
    body=payload(s);body['questions'][0]['source']['version_id']=str(ObjectId())
    assert a.post('/api/surveys',json=body).status_code==422

def test_detach_to_local_question_is_allowed(clients):
    a,_,_=clients;x=create(a);s=a.post('/api/surveys',json={'title':'draft'}).json()
    s=a.post('/api/surveys/'+s['id']+'/import-question?revision=1',json={'version_id':x['version']['id'],'local_id':'age'}).json()
    body=payload(s);body['questions'][0].update(source=None,title='自己改为本地题')
    assert a.put('/api/surveys/'+s['id']+'?revision=2',json=body).status_code==200
    assert not a.get('/api/library/questions/'+x['root']['id']+'/usage').json()['surveys']

def test_import_guards_and_contextual_rules(clients):
    a,_,_=clients;x=create(a);s=a.post('/api/surveys',json={'title':'draft'}).json()
    r=a.post('/api/surveys/'+s['id']+'/import-question?revision=1',json={'version_id':x['version']['id'],'local_id':'age'})
    assert r.status_code==201;r=r.json();assert r['schema_version']==2
    assert a.post('/api/surveys/'+s['id']+'/import-question?revision=2',json={'version_id':x['version']['id'],'local_id':'age'}).status_code==409
    body=payload(r);body['questions'][0]['rules']=[{'op':'gte','value':18,'target':'END'}]
    assert a.put('/api/surveys/'+s['id']+'?revision=2',json=body).status_code==200
    assert a.post('/api/surveys/'+s['id']+'/publish').status_code==200
    assert a.post('/api/surveys/'+s['id']+'/import-question?revision=3',json={'version_id':x['version']['id'],'local_id':'x'}).status_code==409

def test_usage_redaction_and_scope(clients):
    a,b,_=clients;x=create(a);share(a,b,x['root']['id']);survey(a,x['version']['id']);sb=survey(b,x['version']['id'])
    rows=a.get('/api/library/questions/'+x['root']['id']+'/usage').json()['surveys']
    assert len(rows)==2
    assert next(r for r in rows if r['survey_id']==sb['id'])['title']=='其他用户问卷（内容受保护）'
    assert len(b.get('/api/library/questions/'+x['root']['id']+'/usage').json()['surveys'])==1

@pytest.mark.parametrize('kind,values,expected',[('number',[20,40],30),('single',['A','B'],None),('multiple',[['A','B'],['B']],None),('text',['建议一','建议二'],None)])
def test_cross_survey_stats_each_type(clients,kind,values,expected):
    a,_,_=clients;x=create(a,definition(kind));rid=x['root']['id'];v=x['version']
    for i,value in enumerate(values):
        s=survey(a,v['id'],local='local'+str(i));submit(a,s['id'],value,key='local'+str(i))
    r=a.get('/api/library/questions/'+rid+'/stats?limit=1').json()['versions'][0]
    assert r['answered']==2 and r['survey_count']==2
    if kind=='number':assert r['average']==expected and len(r['values'])==1
    if kind=='text':assert len(r['values'])==1
    if kind=='single':assert [o['count'] for o in r['options']]==[1,1,0]
    if kind=='multiple':assert [o['count'] for o in r['options']]==[1,2,0]

def test_stats_all_versions_separate_and_empty(clients):
    a,_,_=clients;x=create(a);v2=version(a,x['root']['id'],x['version']['id'])
    s=survey(a,x['version']['id']);submit(a,s['id'],18)
    r=a.get('/api/library/questions/'+x['root']['id']+'/stats').json()
    assert len(r['versions'])==2 and r['grouping']=='exact_version'
    assert r['versions'][1]['answered']==0 and r['versions'][1]['average'] is None
    assert a.get('/api/library/questions/'+x['root']['id']+'/stats?version_id='+str(ObjectId())).status_code==404

def test_global_aggregate_and_raw_content_privacy(clients):
    a,b,_=clients;x=create(a);rid=x['root']['id'];vid=x['version']['id'];share(a,b,rid)
    sa=survey(a,vid);sb=survey(b,vid);submit(a,sa['id'],20);submit(b,sb['id'],40)
    mine=a.get('/api/library/questions/'+rid+'/stats').json()['versions'][0];assert mine['average']==20
    allrows=a.get('/api/library/questions/'+rid+'/stats?scope=all').json()['versions'][0]
    assert allrows['average']==30 and allrows['answered']==2 and allrows['values']==[20]
    assert b.get('/api/library/questions/'+rid+'/stats?scope=all').status_code==403
    t=create(a,definition('text'));share(a,b,t['root']['id']);s=survey(b,t['version']['id']);submit(b,s['id'],'其他问卷私密文本')
    r=a.get('/api/library/questions/'+t['root']['id']+'/stats?scope=all').json()['versions'][0]
    assert r['answered']==1 and r['values']==[]

def test_banks_add_update_remove_archive(clients):
    a,b,_=clients;x=create(a);rid=x['root']['id'];v=x['version'];bank=a.post('/api/banks',json={'name':'常用题','description':'测试'}).json();bid=bank['id']
    assert b.get('/api/banks/'+bid+'/items').status_code==404
    assert a.post('/api/banks/'+bid+'/items',json={'version_id':v['id']}).status_code==201
    assert a.get('/api/banks').json()[0]['item_count']==1
    v2=version(a,rid,v['id']);item=a.get('/api/banks/'+bid+'/items').json()[0];assert item['has_update'] and item['version']['id']==v['id']
    assert a.post('/api/banks/'+bid+'/items',json={'version_id':v2['id']}).status_code==201
    assert not a.get('/api/banks/'+bid+'/items').json()[0]['has_update']
    assert a.put('/api/banks/'+bid+'?revision=1',json={'name':'新名称'}).status_code==200
    assert a.put('/api/banks/'+bid+'?revision=1',json={'name':'冲突'}).status_code==409
    assert a.delete('/api/banks/'+bid+'/items/'+rid).status_code==200
    assert a.get('/api/banks/'+bid+'/items').json()==[]
    assert a.delete('/api/banks/'+bid).status_code==200
    assert a.get('/api/banks/'+bid+'/items').status_code==404
    assert a.get('/api/library/questions/'+rid).status_code==200

def test_bank_shared_revoke_unavailable(clients):
    a,b,_=clients;x=create(a);rid=x['root']['id'];share(a,b,rid)
    bank=b.post('/api/banks',json={'name':'共享收藏'}).json();b.post('/api/banks/'+bank['id']+'/items',json={'version_id':x['version']['id']})
    a.delete('/api/library/questions/'+rid+'/shares/'+b.get('/api/auth/me').json()['id'])
    assert b.get('/api/banks/'+bank['id']+'/items').json()[0]['available'] is False

def test_fork_shared_question_independent_owner(clients):
    a,b,_=clients;x=create(a);share(a,b,x['root']['id'])
    f=b.post('/api/library/versions/'+x['version']['id']+'/fork',json={'definition':definition(title='我的改编')})
    assert f.status_code==201;f=f.json()
    assert f['root']['derived_from_version_id']==x['version']['id']
    assert b.get('/api/library/questions/'+f['root']['id']).json()['is_owner']
    assert a.get('/api/library/questions/'+x['root']['id']).json()['versions'][0]['definition']['title']=='年龄'

def test_save_existing_does_not_relink_history(clients):
    a,_,_=clients;x=create(a);s=survey(a,x['version']['id']);before=a.get('/api/surveys/'+s['id']).json()
    r=a.post('/api/surveys/'+s['id']+'/questions/age/save-to-library')
    assert r.status_code==201
    assert a.get('/api/surveys/'+s['id']).json()==before

def test_concurrent_new_versions_unique_numbers(clients):
    a,_,_=clients;x=create(a);rid=x['root']['id'];parent=x['version']['id']
    with ThreadPoolExecutor(max_workers=6) as pool:rows=list(pool.map(lambda _:version(a,rid,parent),range(6)))
    assert sorted(r['number'] for r in rows)==list(range(2,8))
    assert len({r['id'] for r in rows})==6

def test_wrong_parent_unknown_recipient_invalid_definition(clients):
    a,_,_=clients;x=create(a);y=create(a)
    r=a.post('/api/library/questions/'+x['root']['id']+'/versions',json={'definition':definition(),'parent_version_id':y['version']['id']})
    assert r.status_code==404
    assert a.post('/api/library/questions/'+x['root']['id']+'/shares',json={'username':'nonexistent_'+uuid.uuid4().hex[:10]}).status_code==404
    assert a.post('/api/library/questions',json={'definition':definition('single',options=['A','A'])}).status_code==422
    assert a.post('/api/banks',json={'name':'   '}).status_code==422

def test_additive_migration_legacy_docs_unchanged(clients):
    a,_,_=clients;database=app.state.db
    # Construct an actual v1 document without source fields, including existing responses.
    s=a.post('/api/surveys',json={'title':'旧问卷','questions':[{'id':'n','title':'旧年龄','type':'number'}]}).json()
    sid=ObjectId(s['id']);database.surveys.update_one({'_id':sid},{'$set':{'schema_version':1},'$unset':{'questions.0.source':''}})
    a.post('/api/surveys/'+s['id']+'/publish');submit(a,s['id'],25,key='n')
    before=database.surveys.find_one({'_id':sid});responses=list(database.responses.find({'survey_id':sid}))
    initialize(database);initialize(database)
    assert database.surveys.find_one({'_id':sid})==before
    assert list(database.responses.find({'survey_id':sid}))==responses
    assert a.get('/api/surveys/'+s['id']+'/stats').json()['questions'][0]['average']==25
    assert database.migrations.count_documents({'_id':'stage2_catalog_v1'})==1

def test_catalog_db_validators_and_indexes(clients):
    database=app.state.db
    for name in ['question_roots','question_versions','question_shares','question_banks','bank_items']:
        assert name in database.list_collection_names()
    assert database.question_versions.index_information()['uq_root_version']['unique']
    assert database.bank_items.index_information()['uq_bank_root']['unique']
    with pytest.raises(WriteError):database.question_versions.insert_one({'definition':[]})

def test_library_auth_and_assets(clients):
    a,_,_=clients
    anon=TestClient(app)
    for url in ['/api/library/questions','/api/banks']:
        assert anon.get(url).status_code==401
    assert a.get('/static/catalog.js').status_code==200
    assert a.get('/api/health').json()['schema_version']==2
    anon.close()

def test_backup_bson_and_manifest(clients,tmp_path):
    from scripts.upgrade import backup
    from bson import decode_all
    import hashlib,json
    database=app.state.db;target=tmp_path/'private_backup'
    result=backup(database,target)
    saved=json.loads((target/'manifest.json').read_text(encoding='utf-8'))
    assert saved['database']==database.name
    for name,info in result['collections'].items():
        raw=(target/(name+'.bson')).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==info['sha256']
        assert len(decode_all(raw))==info['count']==database[name].count_documents({})
    with pytest.raises(FileExistsError):backup(database,target)

def test_optional_unanswered_not_counted(clients):
    a,_,_=clients;x=create(a,definition(required=False));s=survey(a,x['version']['id'])
    submit(a,s['id'],None)
    q=a.get('/api/library/questions/'+x['root']['id']+'/stats').json()['versions'][0]
    assert q['answered']==0 and q['average'] is None

def test_concurrent_grants_idempotent(clients):
    a,b,_=clients;x=create(a);name=b.get('/api/auth/me').json()['username'];rid=x['root']['id']
    with ThreadPoolExecutor(max_workers=6) as pool:
        codes=list(pool.map(lambda _:a.post('/api/library/questions/'+rid+'/shares',json={'username':name}).status_code,range(6)))
    assert codes==[201]*6
    assert len(a.get('/api/library/questions/'+rid+'/shares').json())==1

def test_concurrent_bank_add_no_duplicates(clients):
    a,_,_=clients;x=create(a);bank=a.post('/api/banks',json={'name':'并发题库'}).json()
    with ThreadPoolExecutor(max_workers=6) as pool:
        codes=list(pool.map(lambda _:a.post('/api/banks/'+bank['id']+'/items',json={'version_id':x['version']['id']}).status_code,range(6)))
    assert codes==[201]*6
    assert len(a.get('/api/banks/'+bank['id']+'/items').json())==1

def test_restore_backup_new_database_only(clients,tmp_path):
    from scripts.upgrade import backup
    from scripts.restore_backup import restore
    database=app.state.db;folder=tmp_path/'restore_case';backup(database,folder)
    target='dm_project1_restore_test_'+uuid.uuid4().hex
    client=database.client
    try:
        restored=restore(client,folder,target)
        assert restored.surveys.count_documents({})==database.surveys.count_documents({})
        assert restored.question_versions.index_information()['uq_root_version']['unique']
        with pytest.raises(ValueError):restore(client,folder,target)
        with pytest.raises(ValueError):restore(client,folder,database.name)
    finally:
        assert target.startswith('dm_project1_restore_test_');client.drop_database(target)

def test_corrupt_backup_rejected_before_restore(clients,tmp_path):
    from scripts.upgrade import backup
    from scripts.restore_backup import restore
    database=app.state.db;folder=tmp_path/'corrupt';record=backup(database,folder)
    filename=next(iter(record['collections']))+'.bson';(folder/filename).write_bytes(b'broken')
    target='dm_project1_restore_test_'+uuid.uuid4().hex
    with pytest.raises(ValueError):restore(database.client,folder,target)
    assert not database.client[target].list_collection_names()
