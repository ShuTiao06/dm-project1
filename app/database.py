import os
from pymongo import MongoClient, ASCENDING, DESCENDING


def connect():
    client = MongoClient(os.getenv('MONGODB_URI', 'mongodb://127.0.0.1:27017/'), serverSelectionTimeoutMS=5000, tz_aware=True)
    client.admin.command('ping')
    return client, client[os.getenv('MONGODB_DB','dm_project1')]


def initialize(db):
    """MongoDB enforces core BSON shapes; application enforces conditional rules."""
    definitions = {
        'users': {'required':['username','password_hash','created_at'], 'properties':{'username':{'bsonType':'string'},'password_hash':{'bsonType':'string'},'created_at':{'bsonType':'date'}}},
        'sessions': {'required':['token_hash','user_id','expires_at'], 'properties':{'token_hash':{'bsonType':'string'},'user_id':{'bsonType':'objectId'},'expires_at':{'bsonType':'date'}}},
        'surveys': {'required':['owner_id','title','status','questions','schema_version','revision'], 'properties':{'owner_id':{'bsonType':'objectId'},'title':{'bsonType':'string'},'status':{'enum':['draft','published','closed']},'questions':{'bsonType':'array'},'schema_version':{'enum':[1,2]},'revision':{'bsonType':'int'}}},
        'responses': {'required':['survey_id','survey_revision','respondent_key','request_id','answers','path','submitted_at'], 'properties':{'survey_id':{'bsonType':'objectId'},'survey_revision':{'bsonType':'int'},'respondent_key':{'bsonType':'string'},'answers':{'bsonType':'object'},'path':{'bsonType':'array'},'submitted_at':{'bsonType':'date'}}},
        'question_roots': {'required':['owner_id','next_version','created_at'], 'properties':{'owner_id':{'bsonType':'objectId'},'next_version':{'bsonType':'int'},'created_at':{'bsonType':'date'}}},
        'question_versions': {'required':['root_id','number','definition','fingerprint','created_at'], 'properties':{'root_id':{'bsonType':'objectId'},'number':{'bsonType':'int'},'definition':{'bsonType':'object'},'fingerprint':{'bsonType':'string'},'parent_version_id':{'bsonType':['objectId','null']},'created_at':{'bsonType':'date'}}},
        'question_shares': {'required':['root_id','grantee_id','created_at'], 'properties':{'root_id':{'bsonType':'objectId'},'grantee_id':{'bsonType':'objectId'},'created_at':{'bsonType':'date'}}},
        'question_banks': {'required':['owner_id','name','revision','archived'], 'properties':{'owner_id':{'bsonType':'objectId'},'name':{'bsonType':'string'},'revision':{'bsonType':'int'},'archived':{'bsonType':'bool'}}},
        'bank_items': {'required':['bank_id','root_id','version_id','updated_at'], 'properties':{'bank_id':{'bsonType':'objectId'},'root_id':{'bsonType':'objectId'},'version_id':{'bsonType':'objectId'},'updated_at':{'bsonType':'date'}}},
    }
    existing = db.list_collection_names()
    for name, schema in definitions.items():
        validator = {'$jsonSchema':{'bsonType':'object', **schema}}
        if name not in existing:
            db.create_collection(name, validator=validator)
        else:
            db.command('collMod',name,validator=validator,validationLevel='strict')
    db.users.create_index('username',unique=True,name='uq_username')
    db.sessions.create_index('token_hash',unique=True,name='uq_session_token')
    db.sessions.create_index('expires_at',expireAfterSeconds=0,name='ttl_session')
    db.surveys.create_index([('owner_id',ASCENDING),('created_at',DESCENDING)],name='owner_recent')
    db.surveys.create_index([('status',ASCENDING),('deadline',ASCENDING)],name='status_deadline')
    db.responses.create_index([('survey_id',ASCENDING),('submitted_at',DESCENDING)],name='survey_time')
    db.responses.create_index([('survey_id',ASCENDING),('respondent_key',ASCENDING),('request_id',ASCENDING)],unique=True,name='uq_idempotency')
    db.responses.create_index([('survey_id',ASCENDING),('single_key',ASCENDING)],unique=True,partialFilterExpression={'single_key':{'$type':'string'}},name='uq_single_response')
    db.question_roots.create_index([('owner_id',1),('created_at',-1)],name='root_owner_recent')
    db.question_versions.create_index([('root_id',1),('number',-1)],unique=True,name='uq_root_version')
    db.question_versions.create_index('parent_version_id',name='version_parent')
    db.question_shares.create_index([('root_id',1),('grantee_id',1)],unique=True,name='uq_root_grantee')
    db.question_shares.create_index([('grantee_id',1),('created_at',-1)],name='grantee_roots')
    db.question_banks.create_index([('owner_id',1),('archived',1)],name='owner_active_banks')
    db.bank_items.create_index([('bank_id',1),('root_id',1)],unique=True,name='uq_bank_root')
    db.surveys.create_index('questions.source.root_id',name='question_root_usage')
    db.surveys.create_index('questions.source.version_id',name='question_version_usage')
    # Idempotent additive migration: old surveys/responses remain untouched.
    db.migrations.update_one({'_id':'stage2_catalog_v1'},{'$setOnInsert':{'description':'Added catalog collections and indexes; legacy snapshots retained'}},upsert=True)

