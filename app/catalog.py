from datetime import datetime, timezone
from typing import Literal
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from .main import db, user, public, owned
from .catalog_models import NewLibraryQuestion, NewVersion, ShareInput, ImportInput, BankInput, BankItemInput
from .catalog_service import access_root, access_version, source_for, content, fingerprint, validate_definition, identifier

router=APIRouter(prefix='/api',tags=['第二阶段题库与版本'])
def now():
    value=datetime.now(timezone.utc)
    return value.replace(microsecond=value.microsecond//1000*1000)


def create_root(body,account,database,derived=None):
    definition=body.definition.model_dump()
    validate_definition(definition)
    root={'_id':ObjectId(),'owner_id':account['_id'],'next_version':1,'created_at':now()}
    if derived: root['derived_from_version_id']=derived
    version={'_id':ObjectId(),'root_id':root['_id'],'number':1,'definition':definition,'fingerprint':fingerprint(definition),'parent_version_id':None,'created_at':now(),'note':body.note}
    database.question_roots.insert_one(root)
    database.question_versions.insert_one(version)
    return {'root':public(root),'version':public(version)}


def insert_version(root,parent,definition,note,database,restored=False):
    validate_definition(definition)
    reserved=database.question_roots.find_one_and_update({'_id':root['_id']},{'$inc':{'next_version':1}},return_document=ReturnDocument.AFTER)
    version={'root_id':root['_id'],'number':reserved['next_version'],'definition':definition,'fingerprint':fingerprint(definition),'parent_version_id':parent['_id'],'created_at':now(),'note':note}
    if restored: version['restored_from_version_id']=parent['_id']
    database.question_versions.insert_one(version)
    return public(version)


@router.get('/library/questions')
def library_list(scope:Literal['all','owned','shared']='all',skip:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),account=Depends(user),database=Depends(db)):
    shared=[g['root_id'] for g in database.question_shares.find({'grantee_id':account['_id']})]
    conditions={'owner_id':account['_id']} if scope=='owned' else {'_id':{'$in':shared},'owner_id':{'$ne':account['_id']}} if scope=='shared' else {'$or':[{'owner_id':account['_id']},{'_id':{'$in':shared}}]}
    rows=[]
    for root in database.question_roots.find(conditions).sort('created_at',-1).skip(skip).limit(limit):
        latest=database.question_versions.find_one({'root_id':root['_id']},sort=[('number',-1)])
        if latest: rows.append({**public(root),'is_owner':root['owner_id']==account['_id'],'latest':public(latest)})
    return rows


@router.post('/library/questions',status_code=201)
def new_library(body:NewLibraryQuestion,account=Depends(user),database=Depends(db)):
    return create_root(body,account,database)


@router.get('/library/questions/{rid}')
def detail(rid:str,account=Depends(user),database=Depends(db)):
    root=access_root(rid,account,database)
    versions=list(database.question_versions.find({'root_id':root['_id']}).sort('number',-1))
    return {'root':public(root),'is_owner':root['owner_id']==account['_id'],'versions':public(versions)}


@router.post('/library/questions/{rid}/versions',status_code=201)
def new_version(rid:str,body:NewVersion,account=Depends(user),database=Depends(db)):
    root=access_root(rid,account,database,True)
    parent=database.question_versions.find_one({'_id':identifier(body.parent_version_id),'root_id':root['_id']})
    if not parent: raise HTTPException(404,'父版本不属于该题目')
    return insert_version(root,parent,body.definition.model_dump(),body.note,database)


@router.post('/library/questions/{rid}/versions/{vid}/restore',status_code=201)
def restore(rid:str,vid:str,account=Depends(user),database=Depends(db)):
    root=access_root(rid,account,database,True)
    parent=database.question_versions.find_one({'_id':identifier(vid),'root_id':root['_id']})
    if not parent: raise HTTPException(404,'版本不存在')
    return insert_version(root,parent,parent['definition'],'恢复自 v'+str(parent['number']),database,True)


@router.post('/library/versions/{vid}/fork',status_code=201)
def fork(vid:str,body:NewLibraryQuestion,account=Depends(user),database=Depends(db)):
    _,version=access_version(vid,account,database)
    return create_root(body,account,database,version['_id'])


@router.post('/library/questions/{rid}/shares',status_code=201)
def share(rid:str,body:ShareInput,account=Depends(user),database=Depends(db)):
    root=access_root(rid,account,database,True)
    recipient=database.users.find_one({'username':body.username})
    if not recipient: raise HTTPException(404,'该用户名尚未注册')
    if recipient['_id']==account['_id']: raise HTTPException(422,'无需共享给自己')
    try:
        database.question_shares.update_one({'root_id':root['_id'],'grantee_id':recipient['_id']},{'$setOnInsert':{'created_at':now()}},upsert=True)
    except DuplicateKeyError:
        pass  # Concurrent identical grants are idempotent; the unique row exists.
    return {'username':recipient['username'],'shared':True}


@router.get('/library/questions/{rid}/shares')
def shares(rid:str,account=Depends(user),database=Depends(db)):
    root=access_root(rid,account,database,True)
    grants=list(database.question_shares.find({'root_id':root['_id']}))
    names={u['_id']:u['username'] for u in database.users.find({'_id':{'$in':[g['grantee_id'] for g in grants]}})}
    return [{'user_id':str(g['grantee_id']),'username':names.get(g['grantee_id'],'已失效账号'),'created_at':g['created_at'].isoformat()} for g in grants]


@router.delete('/library/questions/{rid}/shares/{uid}')
def unshare(rid:str,uid:str,account=Depends(user),database=Depends(db)):
    root=access_root(rid,account,database,True)
    database.question_shares.delete_one({'root_id':root['_id'],'grantee_id':identifier(uid)})
    return {'ok':True,'message':'撤销未来取用权限，已导入的问卷快照继续可用'}


@router.post('/surveys/{sid}/import-question',status_code=201)
def import_question(sid:str,body:ImportInput,revision:int=Query(...,ge=1),account=Depends(user),database=Depends(db)):
    survey=owned(sid,account,database)
    _,version=access_version(body.version_id,account,database)
    question={'id':body.local_id,**version['definition'],'rules':[],'source':source_for(version)}
    doc=database.surveys.find_one_and_update({'_id':survey['_id'],'status':'draft','revision':revision,'questions.id':{'$ne':body.local_id},'questions.99':{'$exists':False}}, {'$push':{'questions':question},'$set':{'schema_version':2,'updated_at':now()},'$inc':{'revision':1}},return_document=ReturnDocument.AFTER)
    if not doc: raise HTTPException(409,'草稿版本冲突、题号重复、已发布或题数超限')
    return public(doc)


@router.post('/surveys/{sid}/questions/{qid}/save-to-library',status_code=201)
def save_existing(sid:str,qid:str,account=Depends(user),database=Depends(db)):
    survey=owned(sid,account,database)
    question=next((q for q in survey['questions'] if q['id']==qid),None)
    if not question: raise HTTPException(404,'问卷内题目不存在')
    # Saving a copy never silently relinks published history.
    return create_root(NewLibraryQuestion(definition=content(question),note='保存自问卷 '+sid+' / '+qid),account,database)


@router.get('/library/questions/{rid}/usage')
def usage(rid:str,version_id:str|None=None,account=Depends(user),database=Depends(db)):
    root=access_root(rid,account,database)
    query={'questions.source.root_id':rid}
    owner=root['owner_id']==account['_id']
    if not owner: query['owner_id']=account['_id']
    rows=[]
    for survey in database.surveys.find(query,{'title':1,'status':1,'owner_id':1,'questions':1}):
        local=[{'question_id':q['id'],'version_id':q['source']['version_id']} for q in survey['questions'] if q.get('source',{} ) and q['source']['root_id']==rid and (not version_id or q['source']['version_id']==version_id)]
        if local:
            mine=survey['owner_id']==account['_id']
            rows.append({'survey_id':str(survey['_id']),'title':survey['title'] if mine else '其他用户问卷（内容受保护）','status':survey['status'],'is_owner':mine,'questions':local})
    return {'root_id':rid,'surveys':rows,'scope':'all_usage_redacted' if owner else 'own_surveys'}


@router.get('/banks')
def banks(account=Depends(user),database=Depends(db)):
    rows=list(database.question_banks.find({'owner_id':account['_id'],'archived':False}).sort('created_at',-1))
    for row in rows: row['item_count']=database.bank_items.count_documents({'bank_id':row['_id']})
    return public(rows)


@router.post('/banks',status_code=201)
def create_bank(body:BankInput,account=Depends(user),database=Depends(db)):
    doc={**body.model_dump(),'owner_id':account['_id'],'revision':1,'archived':False,'created_at':now()}
    database.question_banks.insert_one(doc)
    return public(doc)


def owned_bank(bid,account,database):
    bank=database.question_banks.find_one({'_id':identifier(bid),'owner_id':account['_id'],'archived':False})
    if not bank: raise HTTPException(404,'题库不存在或无权访问')
    return bank


@router.put('/banks/{bid}')
def rename_bank(bid:str,body:BankInput,revision:int=Query(...,ge=1),account=Depends(user),database=Depends(db)):
    owned_bank(bid,account,database)
    bank=database.question_banks.find_one_and_update({'_id':identifier(bid),'revision':revision,'archived':False},{'$set':body.model_dump(),'$inc':{'revision':1}},return_document=ReturnDocument.AFTER)
    if not bank: raise HTTPException(409,'题库版本冲突')
    return public(bank)


@router.delete('/banks/{bid}')
def archive_bank(bid:str,account=Depends(user),database=Depends(db)):
    bank=owned_bank(bid,account,database)
    database.question_banks.update_one({'_id':bank['_id']},{'$set':{'archived':True},'$inc':{'revision':1}})
    return {'ok':True,'message':'题库已归档，不删除题目版本和历史问卷'}


@router.get('/banks/{bid}/items')
def bank_items(bid:str,account=Depends(user),database=Depends(db)):
    bank=owned_bank(bid,account,database)
    rows=[]
    for item in database.bank_items.find({'bank_id':bank['_id']}).sort('updated_at',-1):
        try:
            root,version=access_version(str(item['version_id']),account,database)
            latest=database.question_versions.find_one({'root_id':root['_id']},sort=[('number',-1)])
            rows.append({**public(item),'available':True,'version':public(version),'latest_version_id':str(latest['_id']),'has_update':latest['_id']!=version['_id']})
        except HTTPException:
            rows.append({**public(item),'available':False,'message':'共享已撤销，无法继续取用；已有问卷快照不受影响'})
    return rows


@router.post('/banks/{bid}/items',status_code=201)
def add_bank_item(bid:str,body:BankItemInput,account=Depends(user),database=Depends(db)):
    bank=owned_bank(bid,account,database)
    root,version=access_version(body.version_id,account,database)
    key={'bank_id':bank['_id'],'root_id':root['_id']}
    try:
        doc=database.bank_items.find_one_and_update(key,{'$set':{'version_id':version['_id'],'updated_at':now()}},upsert=True,return_document=ReturnDocument.AFTER)
    except DuplicateKeyError:
        doc=database.bank_items.find_one_and_update(key,{'$set':{'version_id':version['_id'],'updated_at':now()}},return_document=ReturnDocument.AFTER)
    return public(doc)


@router.delete('/banks/{bid}/items/{rid}')
def remove_bank_item(bid:str,rid:str,account=Depends(user),database=Depends(db)):
    bank=owned_bank(bid,account,database)
    database.bank_items.delete_one({'bank_id':bank['_id'],'root_id':identifier(rid)})
    return {'ok':True}


def observation_pipeline(rid,vid,account,scope):
    match={'questions.source.root_id':rid}
    if scope=='mine': match['owner_id']=account['_id']
    return [{'$match':match},{'$unwind':'$questions'},{'$match':{'questions.source.version_id':vid}},
        {'$lookup':{'from':'responses','localField':'_id','foreignField':'survey_id','as':'response'}},{'$unwind':'$response'},
        {'$project':{'survey_id':'$_id','local_id':'$questions.id','mine':{'$eq':['$owner_id',account['_id']]},'submitted_at':'$response.submitted_at','kv':{'$arrayElemAt':[{'$filter':{'input':{'$objectToArray':'$response.answers'},'as':'pair','cond':{'$eq':['$$pair.k','$questions.id']}}},0]}}},
        {'$match':{'kv.v':{'$exists':True}}},{'$project':{'_id':0,'survey_id':1,'local_id':1,'mine':1,'submitted_at':1,'value':'$kv.v'}}]


@router.get('/library/questions/{rid}/stats')
def catalog_stats(rid:str,scope:Literal['mine','all']='mine',version_id:str|None=None,skip:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=1000),account=Depends(user),database=Depends(db)):
    root=access_root(rid,account,database)
    if scope=='all' and root['owner_id']!=account['_id']: raise HTTPException(403,'只有题目所有者可查看全局聚合；其他用户仅可统计自己的问卷')
    query={'root_id':root['_id']}
    if version_id: query['_id']=identifier(version_id)
    versions=list(database.question_versions.find(query).sort('number',1))
    if version_id and not versions: raise HTTPException(404,'版本不属于该题')
    results=[]
    for version in versions:
        pipeline=observation_pipeline(rid,str(version['_id']),account,scope)
        counts=list(database.surveys.aggregate(pipeline+[{'$group':{'_id':None,'answered':{'$sum':1},'surveys':{'$addToSet':'$survey_id'}}}]))
        item={'version_id':str(version['_id']),'number':version['number'],'fingerprint':version['fingerprint'],'definition':version['definition'],'answered':counts[0]['answered'] if counts else 0,'survey_count':len(counts[0]['surveys']) if counts else 0}
        kind=version['definition']['type']
        if kind in ('single','multiple'):
            stages=pipeline+([{'$unwind':'$value'}] if kind=='multiple' else [])+[{'$group':{'_id':'$value','count':{'$sum':1}}}]
            values={x['_id']:x['count'] for x in database.surveys.aggregate(stages)}
            item['options']=[{'label':o,'count':values.get(o,0)} for o in version['definition']['options']]
        else:
            # Global aggregates never reveal another author's raw free text.
            own=pipeline+([{'$match':{'mine':True}}] if scope=='all' else [])
            vals=list(database.surveys.aggregate(own+[{'$sort':{'submitted_at':-1,'survey_id':1,'local_id':1}},{'$skip':skip},{'$limit':limit}]))
            item.update(values=[x['value'] for x in vals],skip=skip,limit=limit,values_scope='own_surveys')
            own_count=list(database.surveys.aggregate(own+[{'$count':'n'}]))
            item['own_values_count']=own_count[0]['n'] if own_count else 0
            if kind=='number':
                numbers=list(database.surveys.aggregate(pipeline+[{'$group':{'_id':None,'average':{'$avg':'$value'},'min':{'$min':'$value'},'max':{'$max':'$value'}}}]))
                item.update({k:numbers[0][k] if numbers else None for k in ['average','min','max']})
        results.append(item)
    return {'root_id':rid,'scope':scope,'grouping':'exact_version','versions':results,'notice':'按确切题目版本统计，不合并不同含义版本；全局仅共享聚合，原始填空内容仅来自自己的问卷。'}
