"""Integration tests use real MongoDB in an isolated, disposable database."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient
from app.main import app

@pytest.fixture(scope='module')
def client():
    name='dm_project1_test_'+uuid.uuid4().hex
    old=os.environ.get('MONGODB_DB')
    os.environ['MONGODB_DB']=name
    try:
        with TestClient(app) as c:yield c
    finally:
        mongo=MongoClient(os.getenv('MONGODB_URI','mongodb://127.0.0.1:27017/'))
        assert name.startswith('dm_project1_test_') and len(name)==49
        mongo.drop_database(name);mongo.close()
        if old is None:os.environ.pop('MONGODB_DB',None)
        else:os.environ['MONGODB_DB']=old

def login(c,name=None):
    name=name or 'u_'+uuid.uuid4().hex[:12]
    body={'username':name,'password':'TestPass123!'}
    assert c.post('/api/auth/register',json=body).status_code==201
    assert c.post('/api/auth/login',json=body).status_code==200
    return body

def sample(**extra):
    return {'title':'分支问卷','allow_anonymous':True,'allow_multiple':False,'questions':[
        {'id':'q1','title':'单选','type':'single','options':['A','B'],'rules':[{'op':'eq','value':'A','target':'q3'}]},
        {'id':'q2','title':'文本','type':'text','validation':{'min_length':2}},
        {'id':'q3','title':'年龄','type':'number','validation':{'integer':True,'min_value':0,'max_value':120}},
        {'id':'q4','title':'多选','type':'multiple','options':['X','Y','Z'],'validation':{'min_choices':1,'max_choices':2}}
    ],**extra}

def create_publish(c,**extra):
    r=c.post('/api/surveys',json=sample(**extra));assert r.status_code==201,r.text
    sid=r.json()['id']
    assert c.post('/api/surveys/'+sid+'/publish').status_code==200
    return sid

def response(c,sid,**kw):
    return c.post('/api/public/surveys/'+sid+'/responses',json={'answers':{'q1':'A','q3':18,'q4':['X','Y']},'anonymous':True,'request_id':uuid.uuid4().hex,**kw})

def test_health_and_schema(client):
    assert client.get('/api/health').json()['status']=='ok'
    indexes=app.state.db.responses.index_information()
    assert indexes['uq_single_response']['unique'] and indexes['uq_idempotency']['unique']
    assert 'validator' in app.state.db.command('listCollections',filter={'name':'responses'})['cursor']['firstBatch'][0]['options']

def test_login_required(client):
    client.cookies.clear()
    assert client.get('/api/surveys').status_code==401

def test_register_duplicate_wrong_password_logout(client):
    body=login(client)
    assert client.post('/api/auth/register',json=body).status_code==409
    assert client.post('/api/auth/login',json={**body,'password':'WrongPass123'}).status_code==401
    assert client.get('/api/auth/me').status_code==200
    client.post('/api/auth/logout');assert client.get('/api/auth/me').status_code==401

def test_password_never_plaintext(client):
    body=login(client)
    user=app.state.db.users.find_one({'username':body['username']})
    assert body['password'] not in user['password_hash'] and ':' in user['password_hash']
    assert 'password_hash' not in client.get('/api/auth/me').json()

def test_create_add_question_revision(client):
    login(client)
    r=client.post('/api/surveys',json={'title':'空白草稿'}).json();sid=r['id']
    assert client.post('/api/surveys/'+sid+'/check').json()['valid'] is False
    q={'id':'t1','title':'文本','type':'text'}
    r=client.post('/api/surveys/'+sid+'/questions?revision=1',json=q)
    assert r.status_code==200 and r.json()['revision']==2
    assert client.put('/api/surveys/'+sid+'?revision=1',json={'title':'冲突'}).status_code==409
    assert client.post('/api/surveys/'+sid+'/questions?revision=2',json=q).status_code==409

def test_preflight_and_immutable(client):
    login(client);sid=create_publish(client)
    assert client.post('/api/surveys/'+sid+'/check').json()['valid']
    assert client.put('/api/surveys/'+sid+'?revision=1',json=sample()).status_code==409
    assert client.post('/api/surveys/'+sid+'/questions?revision=1',json={'id':'new','title':'x','type':'text'}).status_code==409

def test_owner_isolation(client):
    login(client);sid=create_publish(client)
    login(client)
    assert sid not in [x['id'] for x in client.get('/api/surveys').json()]
    for path in ['', '/stats','/responses']:
        assert client.get('/api/surveys/'+sid+path).status_code==404
    assert client.post('/api/surveys/'+sid+'/close').status_code==404
    assert client.get('/api/public/surveys/'+sid).status_code==200

def test_submission_stats_anonymity_idempotency(client):
    login(client);sid=create_publish(client)
    req=uuid.uuid4().hex
    first=response(client,sid,request_id=req);assert first.status_code==201,first.text
    replay=response(client,sid,request_id=req);assert replay.json()['id']==first.json()['id'] and replay.json()['replayed']
    assert response(client,sid).status_code==409
    stats=client.get('/api/surveys/'+sid+'/stats').json()
    assert stats['total_responses']==1
    qs={q['question_id']:q for q in stats['questions']}
    assert qs['q1']['options'][0]['count']==1 and qs['q1']['options'][1]['count']==0
    assert qs['q2']['answered']==0 and qs['q3']['average']==18
    assert qs['q4']['options'][0]['count']==1 and qs['q4']['options'][1]['count']==1
    rows=client.get('/api/surveys/'+sid+'/responses').json()
    assert 'user_id' not in rows[0] and 'respondent_key' not in rows[0] and 'single_key' not in rows[0]

def test_multiple_submissions_numeric_average_and_text(client):
    login(client);sid=create_publish(client,allow_multiple=True)
    assert response(client,sid,answers={'q1':'B','q2':'很好','q3':20,'q4':['X']},anonymous=False).status_code==201
    assert response(client,sid,answers={'q1':'B','q2':'继续加油','q3':40,'q4':['Z']}).status_code==201
    data=client.get('/api/surveys/'+sid+'/stats?question_id=q3&limit=1').json()
    assert data['questions'][0]['average']==30 and len(data['questions'][0]['values'])==1
    assert client.get('/api/surveys/'+sid+'/stats?question_id=q2').json()['questions'][0]['answered']==2
    rows=client.get('/api/surveys/'+sid+'/responses').json()
    assert any('user_id' in r for r in rows)

@pytest.mark.parametrize('answers',[
    {'q1':'A','q3':18.5,'q4':['X']},
    {'q1':'A','q2':'伪造跳题答案','q3':18,'q4':['X']},
    {'q1':'B','q3':18,'q4':['X']},
    {'q1':'A','q3':18,'q4':['X','X']},
    {'q1':'A','q3':True,'q4':['X']},
])
def test_invalid_submission_rejected(client,answers):
    login(client);sid=create_publish(client)
    assert response(client,sid,answers=answers).status_code==422
    assert client.get('/api/surveys/'+sid+'/stats').json()['total_responses']==0

def test_preview_next(client):
    login(client);sid=create_publish(client)
    r=client.post('/api/public/surveys/'+sid+'/next',json={'answers':{'q1':'A'}})
    assert r.status_code==200 and r.json()['next_question']['id']=='q3'

def test_deadline_and_close(client):
    login(client);sid=create_publish(client)
    assert client.post('/api/surveys/'+sid+'/close').status_code==200
    assert response(client,sid).status_code==409
    sid=create_publish(client,deadline=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    from bson import ObjectId
    app.state.db.surveys.update_one({'_id':ObjectId(sid)},{'$set':{'deadline':datetime.now(timezone.utc)-timedelta(seconds=1)}})
    assert response(client,sid).status_code==409
    assert not client.get('/api/public/surveys/'+sid).json()['accepting']

def test_past_deadline_publish_blocked(client):
    login(client)
    s=client.post('/api/surveys',json=sample(deadline='2000-01-01T00:00:00+08:00')).json()
    assert client.post('/api/surveys/'+s['id']+'/publish').status_code==422

def test_anonymous_disabled(client):
    login(client);sid=create_publish(client,allow_anonymous=False)
    assert response(client,sid).status_code==422
    assert response(client,sid,anonymous=False).status_code==201

def test_concurrent_single_submission(client):
    login(client);sid=create_publish(client)
    def one(i):return response(client,sid).status_code
    with ThreadPoolExecutor(max_workers=6) as pool:codes=list(pool.map(one,range(6)))
    assert codes.count(201)==1 and codes.count(409)==5
    assert client.get('/api/surveys/'+sid+'/stats').json()['total_responses']==1

def test_concurrent_multiple_submission(client):
    login(client);sid=create_publish(client,allow_multiple=True)
    with ThreadPoolExecutor(max_workers=6) as pool:codes=list(pool.map(lambda _:response(client,sid).status_code,range(12)))
    assert codes==[201]*12
    assert client.get('/api/surveys/'+sid+'/stats').json()['total_responses']==12

def test_csrf_and_invalid_id(client):
    assert client.post('/api/auth/logout',headers={'Origin':'https://evil.example'}).status_code==403
    login(client)
    assert client.get('/api/surveys/not-an-id').status_code==404
    assert client.post('/api/surveys',json={'title':'x','deadline':'2026-10-23T23:00:00'}).status_code==422

def test_page_and_assets(client):
    assert client.get('/').status_code==200
    assert client.get('/static/app.js').status_code==200
    assert client.get('/static/style.css').status_code==200
    assert 'Content-Security-Policy' in client.get('/').headers

def test_concurrent_idempotency(client):
    login(client);sid=create_publish(client,allow_multiple=True);key=uuid.uuid4().hex
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(lambda _:response(client,sid,request_id=key),range(6)))
    assert all(r.status_code==201 for r in results)
    assert len({r.json()['id'] for r in results})==1
    assert client.get('/api/surveys/'+sid+'/stats').json()['total_responses']==1

def test_database_validator_rejects_bad_document(client):
    from pymongo.errors import WriteError
    with pytest.raises(WriteError):app.state.db.responses.insert_one({'answers':123})

def test_bad_rules_cannot_publish(client):
    login(client);body=sample();body['questions'][0]['rules'][0]['target']='q1'
    s=client.post('/api/surveys',json=body).json()
    assert client.post('/api/surveys/'+s['id']+'/publish').status_code==422

def test_draft_not_public_and_session_expiry(client):
    login(client);s=client.post('/api/surveys',json=sample()).json()
    assert client.get('/api/public/surveys/'+s['id']).status_code==404
    me=client.get('/api/auth/me').json()
    from bson import ObjectId
    app.state.db.sessions.update_many({'user_id':ObjectId(me['id'])},{'$set':{'expires_at':datetime.now(timezone.utc)-timedelta(seconds=1)}})
    assert client.get('/api/auth/me').status_code==401

def test_multiple_people_can_submit(client):
    login(client);sid=create_publish(client)
    assert response(client,sid).status_code==201
    login(client)
    assert response(client,sid).status_code==201
    from bson import ObjectId
    assert app.state.db.responses.count_documents({'survey_id':ObjectId(sid)})==2

