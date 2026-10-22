from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import hmac
import os
import secrets
from urllib.parse import urlparse

from bson import ObjectId
from fastapi import FastAPI, Depends, HTTPException, Request, Response, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from .database import connect, initialize
from .models import Account, SurveyInput, Submission, Preview, Question
from .engine import inspect_rules, walk, AnswerError

UTC = timezone.utc
ROOT = Path(__file__).parent
def now(): return datetime.now(UTC)
def digest(s): return hashlib.sha256(s.encode()).hexdigest()
def oid(s):
    if not ObjectId.is_valid(s): raise HTTPException(404,'资源不存在')
    return ObjectId(s)
def public(doc):
    if isinstance(doc,list): return [public(x) for x in doc]
    if isinstance(doc,dict): return {('id' if k=='_id' else k):public(v) for k,v in doc.items() if k not in ('password_hash','token_hash')}
    if isinstance(doc,ObjectId): return str(doc)
    if isinstance(doc,datetime): return doc.isoformat()
    return doc
def password_hash(password):
    salt = secrets.token_hex(16)
    return salt + ':' + hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),260000).hex()
def password_ok(password, stored):
    salt, expected = stored.split(':')
    actual = hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),260000).hex()
    return hmac.compare_digest(actual,expected)


@asynccontextmanager
async def lifespan(app):
    client, db = connect()
    initialize(db)
    app.state.db = db
    yield
    client.close()

app = FastAPI(title='问序 SurveyFlow · 第一阶段',version='1.0.0',lifespan=lifespan)
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

@app.middleware('http')
async def same_origin(request:Request, call_next):
    if request.method in ('POST','PUT','DELETE','PATCH'):
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse(status_code=403,content={'detail':'拒绝跨站写入请求'})
        length = request.headers.get('content-length')
        if length and int(length)>1_000_000:
            return JSONResponse(status_code=413,content={'detail':'请求不能超过1MB'})
    result = await call_next(request)
    result.headers['X-Content-Type-Options']='nosniff'
    result.headers['X-Frame-Options']='DENY'
    result.headers['Referrer-Policy']='same-origin'
    policy="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    if request.url.path in ('/docs','/redoc'):
        policy="default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'; frame-ancestors 'none'"
    result.headers['Content-Security-Policy']=policy
    if request.url.path.startswith('/api'): result.headers['Cache-Control']='no-store'
    return result

@app.exception_handler(AnswerError)
async def answer_error(request,exc):
    return JSONResponse(status_code=422,content={'detail':str(exc),'question_id':exc.question_id})

@app.exception_handler(PyMongoError)
async def mongo_error(request,exc):
    return JSONResponse(status_code=503,content={'detail':'数据库暂不可用，请检查 MongoDB 服务后重试'})

def db(request:Request): return request.app.state.db
def user(request:Request, database=Depends(db)):
    token = request.cookies.get('session','')
    session = database.sessions.find_one({'token_hash':digest(token),'expires_at':{'$gt':now()}})
    if not session: raise HTTPException(401,'请先登录')
    account = database.users.find_one({'_id':session['user_id']})
    if not account: raise HTTPException(401,'账号不存在')
    return account
def owned(sid,account,database):
    survey=database.surveys.find_one({'_id':oid(sid),'owner_id':account['_id']})
    if not survey: raise HTTPException(404,'问卷不存在或无权访问')
    return survey
def published(sid,database):
    survey=database.surveys.find_one({'_id':oid(sid),'status':{'$ne':'draft'}})
    if not survey: raise HTTPException(404,'问卷尚未发布或不存在')
    return survey
def accepting(survey):
    if survey['status']!='published': raise HTTPException(409,'问卷已关闭')
    if survey.get('deadline') and survey['deadline']<=now(): raise HTTPException(409,'问卷已截止')
def check(survey):
    result=inspect_rules(survey['questions'])
    if survey.get('deadline') and survey['deadline']<=now():
        result['errors'].append('截止时间必须晚于当前时间')
        result['valid']=False
    return result

@app.get('/')
@app.get('/survey/{sid}')
def home(sid:str=''):
    return FileResponse(ROOT/'static'/'index.html')

@app.get('/api/health')
def health(database=Depends(db)):
    database.command('ping')
    return {'status':'ok','database':database.name,'schema_version':1}

@app.post('/api/auth/register',status_code=201)
def register(body:Account,database=Depends(db)):
    doc={'username':body.username,'password_hash':password_hash(body.password),'created_at':now()}
    try: database.users.insert_one(doc)
    except DuplicateKeyError: raise HTTPException(409,'用户名已被注册')
    return public(doc)

@app.post('/api/auth/login')
def login(body:Account,response:Response,request:Request,database=Depends(db)):
    account=database.users.find_one({'username':body.username})
    if not account or not password_ok(body.password,account['password_hash']): raise HTTPException(401,'用户名或密码错误')
    token=secrets.token_urlsafe(32)
    hours=int(os.getenv('SESSION_HOURS','24'))
    database.sessions.insert_one({'token_hash':digest(token),'user_id':account['_id'],'expires_at':now()+timedelta(hours=hours)})
    response.set_cookie('session',token,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=hours*3600)
    return public(account)

@app.post('/api/auth/logout')
def logout(request:Request,response:Response,database=Depends(db)):
    database.sessions.delete_one({'token_hash':digest(request.cookies.get('session',''))})
    response.delete_cookie('session')
    return {'ok':True}

@app.get('/api/auth/me')
def me(account=Depends(user)): return public(account)

@app.get('/api/surveys')
def list_surveys(account=Depends(user),database=Depends(db),skip:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100)):
    return public(list(database.surveys.find({'owner_id':account['_id']},{'questions':0}).sort('created_at',-1).skip(skip).limit(limit)))

@app.post('/api/surveys',status_code=201)
def create(body:SurveyInput,account=Depends(user),database=Depends(db)):
    doc=body.model_dump()
    doc.update(owner_id=account['_id'],status='draft',schema_version=1,revision=1,created_at=now(),updated_at=now(),submission_seq=0)
    database.surveys.insert_one(doc)
    return public(doc)

@app.get('/api/surveys/{sid}')
def get_survey(sid:str,account=Depends(user),database=Depends(db)):
    return public(owned(sid,account,database))

@app.put('/api/surveys/{sid}')
def update(sid:str,body:SurveyInput,revision:int=Query(...,ge=1),account=Depends(user),database=Depends(db)):
    owned(sid,account,database)
    result=database.surveys.find_one_and_update({'_id':oid(sid),'owner_id':account['_id'],'status':'draft','revision':revision},{'$set':{**body.model_dump(),'updated_at':now()},'$inc':{'revision':1}},return_document=ReturnDocument.AFTER)
    if not result: raise HTTPException(409,'仅可修改草稿，或版本已变化，请刷新后重试')
    return public(result)

@app.post('/api/surveys/{sid}/questions')
def add_question(sid:str,body:Question,revision:int=Query(...,ge=1),account=Depends(user),database=Depends(db)):
    survey=owned(sid,account,database)
    if any(q['id']==body.id for q in survey['questions']): raise HTTPException(409,'题目 ID 已存在')
    result=database.surveys.find_one_and_update({'_id':oid(sid),'status':'draft','revision':revision,'questions.id':{'$ne':body.id},'questions.99':{'$exists':False}}, {'$push':{'questions':body.model_dump()},'$inc':{'revision':1},'$set':{'updated_at':now()}},return_document=ReturnDocument.AFTER)
    if not result: raise HTTPException(409,'草稿版本冲突、已发布或题目超过100道')
    return public(result)

@app.post('/api/surveys/{sid}/check')
def preflight(sid:str,account=Depends(user),database=Depends(db)):
    return check(owned(sid,account,database))

@app.post('/api/surveys/{sid}/publish')
def publish(sid:str,account=Depends(user),database=Depends(db)):
    survey=owned(sid,account,database)
    result=check(survey)
    if not result['valid']: raise HTTPException(422,result)
    doc=database.surveys.find_one_and_update({'_id':oid(sid),'status':'draft','revision':survey['revision']},{'$set':{'status':'published','published_at':now(),'updated_at':now()}},return_document=ReturnDocument.AFTER)
    if not doc: raise HTTPException(409,'问卷已发布或版本冲突')
    return {'survey':public(doc),'url':'/survey/'+sid,'preflight':result}

@app.post('/api/surveys/{sid}/close')
def close(sid:str,account=Depends(user),database=Depends(db)):
    owned(sid,account,database)
    doc=database.surveys.find_one_and_update({'_id':oid(sid),'status':'published'},{'$set':{'status':'closed','closed_at':now(),'updated_at':now()}},return_document=ReturnDocument.AFTER)
    if not doc: raise HTTPException(409,'只有已发布的问卷可关闭')
    return public(doc)

@app.get('/api/public/surveys/{sid}')
def read_public(sid:str,account=Depends(user),database=Depends(db)):
    survey=published(sid,database)
    survey.pop('owner_id',None)
    survey['accepting']=survey['status']=='published' and (not survey.get('deadline') or survey['deadline']>now())
    return public(survey)

@app.post('/api/public/surveys/{sid}/next')
def next_question(sid:str,body:Preview,account=Depends(user),database=Depends(db)):
    survey=published(sid,database)
    accepting(survey)
    return walk(survey['questions'],body.answers)

@app.post('/api/public/surveys/{sid}/responses',status_code=201)
def submit(sid:str,body:Submission,account=Depends(user),database=Depends(db)):
    survey=published(sid,database)
    key=digest(sid+':'+str(account['_id']))
    lookup={'survey_id':survey['_id'],'respondent_key':key,'request_id':body.request_id}
    existing=database.responses.find_one(lookup)
    if existing:
        return {'id':str(existing['_id']),'replayed':True}
    accepting(survey)
    if body.anonymous and not survey['allow_anonymous']: raise HTTPException(422,'此问卷不允许匿名提交')
    result=walk(survey['questions'],body.answers,complete=True)
    # The atomic update is the admission point relative to close/deadline.
    admitted=database.surveys.find_one_and_update({'_id':survey['_id'],'status':'published','$or':[{'deadline':None},{'deadline':{'$gt':now()}}]}, {'$inc':{'submission_seq':1}},return_document=ReturnDocument.AFTER)
    if not admitted: raise HTTPException(409,'问卷已关闭或截止')
    doc={**lookup,'survey_revision':survey['revision'],'anonymous':body.anonymous,'answers':result['answers'],'path':result['path'],'trace':result['trace'],'submitted_at':now()}
    if not body.anonymous: doc['user_id']=account['_id']
    if not survey['allow_multiple']: doc['single_key']=key
    try:
        database.responses.insert_one(doc)
    except DuplicateKeyError:
        existing=database.responses.find_one(lookup)
        if existing: return {'id':str(existing['_id']),'replayed':True}
        raise HTTPException(409,'该问卷每人仅允许提交一次')
    return {'id':str(doc['_id']),'replayed':False,'path':result['path']}

def question_stats(survey,q,database,skip,limit):
    base=[{'$match':{'survey_id':survey['_id'],('answers.'+q['id']):{'$exists':True}}}]
    field='$answers.'+q['id']
    total=database.responses.count_documents({'survey_id':survey['_id'],('answers.'+q['id']):{'$exists':True}})
    result={'question_id':q['id'],'title':q['title'],'type':q['type'],'answered':total}
    if q['type'] in ('single','multiple'):
        stages=base+([{'$unwind':field}] if q['type']=='multiple' else [])+[{'$group':{'_id':field,'count':{'$sum':1}}}]
        counts={x['_id']:x['count'] for x in database.responses.aggregate(stages)}
        result['options']=[{'label':o,'count':counts.get(o,0)} for o in q['options']]
    else:
        rows=list(database.responses.aggregate(base+[{'$sort':{'submitted_at':-1}},{'$skip':skip},{'$limit':limit},{'$project':{'_id':0,'value':field}}]))
        result.update(values=[x['value'] for x in rows],skip=skip,limit=limit)
        if q['type']=='number':
            agg=list(database.responses.aggregate(base+[{'$group':{'_id':None,'average':{'$avg':field},'min':{'$min':field},'max':{'$max':field}}}]))
            result.update({k:agg[0][k] if agg else None for k in ['average','min','max']})
    return result

@app.get('/api/surveys/{sid}/stats')
def stats(sid:str,question_id:str|None=None,skip:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=1000),account=Depends(user),database=Depends(db)):
    survey=owned(sid,account,database)
    qs=[q for q in survey['questions'] if question_id is None or q['id']==question_id]
    if question_id and not qs: raise HTTPException(404,'题目不存在')
    return {'survey_id':sid,'title':survey['title'],'total_responses':database.responses.count_documents({'survey_id':survey['_id']}),'questions':[question_stats(survey,q,database,skip,limit) for q in qs]}

@app.get('/api/surveys/{sid}/responses')
def list_responses(sid:str,skip:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),account=Depends(user),database=Depends(db)):
    owned(sid,account,database)
    # Internal deduplication keys never leave the server.
    return public(list(database.responses.find({'survey_id':oid(sid)},{'respondent_key':0,'single_key':0,'request_id':0}).sort('submitted_at',-1).skip(skip).limit(limit)))
