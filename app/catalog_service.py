"""Version identity and snapshot binding, independent of HTTP routing."""
import hashlib
import json
from bson import ObjectId
from fastapi import HTTPException
from .catalog_models import Definition
from .engine import inspect_rules


def identifier(value):
    if not ObjectId.is_valid(value): raise HTTPException(404,'资源不存在')
    return ObjectId(value)


def content(question):
    return Definition(**{k:question[k] for k in ['title','type','required','options','validation']}).model_dump()


def fingerprint(definition):
    return hashlib.sha256(json.dumps(definition,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def validate_definition(definition):
    result=inspect_rules([{'id':'item',**definition,'rules':[]}])
    if not result['valid']: raise HTTPException(422,result)


def access_root(root_id,account,database,owner_only=False):
    root=database.question_roots.find_one({'_id':identifier(root_id)})
    allowed=root and (root['owner_id']==account['_id'] or (not owner_only and database.question_shares.find_one({'root_id':root['_id'],'grantee_id':account['_id']})))
    if not allowed: raise HTTPException(404,'题目不存在或没有权限')
    return root


def access_version(version_id,account,database):
    version=database.question_versions.find_one({'_id':identifier(version_id)})
    if not version: raise HTTPException(404,'题目版本不存在')
    root=access_root(str(version['root_id']),account,database)
    return root,version


def source_for(version):
    return {'root_id':str(version['root_id']),'version_id':str(version['_id']),'fingerprint':version['fingerprint']}


def bind_sources(questions,account,database,existing=None):
    """Never trust a client-provided source label for cross-survey aggregation."""
    old_sources={q['id']:q.get('source') for q in (existing or {}).get('questions',[]) if q.get('source')}
    for question in questions:
        source=question.get('source')
        if source is None: continue
        version=database.question_versions.find_one({'_id':identifier(source['version_id']),'root_id':identifier(source['root_id'])})
        if not version or source!=source_for(version) or content(question)!=version['definition']:
            raise HTTPException(422,'引用题目的内容与不可变版本不一致；请另存新版本，或解除引用作为本地题')
        if source != old_sources.get(question['id']):
            access_root(source['root_id'],account,database)
    return questions
