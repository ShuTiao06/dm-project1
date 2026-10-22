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
        'surveys': {'required':['owner_id','title','status','questions','schema_version','revision'], 'properties':{'owner_id':{'bsonType':'objectId'},'title':{'bsonType':'string'},'status':{'enum':['draft','published','closed']},'questions':{'bsonType':'array'},'schema_version':{'enum':[1]},'revision':{'bsonType':'int'}}},
        'responses': {'required':['survey_id','survey_revision','respondent_key','request_id','answers','path','submitted_at'], 'properties':{'survey_id':{'bsonType':'objectId'},'survey_revision':{'bsonType':'int'},'respondent_key':{'bsonType':'string'},'answers':{'bsonType':'object'},'path':{'bsonType':'array'},'submitted_at':{'bsonType':'date'}}},
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

