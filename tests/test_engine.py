import pytest
from app.engine import inspect_rules, walk, AnswerError, validate_answer
from app.models import SurveyInput

def questions():
    return SurveyInput(title='test',questions=[
        {'id':'q1','title':'选择','type':'single','options':['A','B'],'rules':[{'op':'eq','value':'A','target':'q3'}]},
        {'id':'q2','title':'文本','type':'text','validation':{'min_length':2,'max_length':4}},
        {'id':'q3','title':'数字','type':'number','validation':{'integer':True,'min_value':0,'max_value':120}},
    ]).model_dump()['questions']

def test_single_branch_skips_required_question():
    r=walk(questions(),{'q1':'A','q3':18},True)
    assert r['path']==['q1','q3'] and 'q2' not in r['answers']

def test_sequential_branch_requires_text():
    with pytest.raises(AnswerError):walk(questions(),{'q1':'B','q3':18},True)

def test_stale_hidden_answer_rejected():
    with pytest.raises(AnswerError):walk(questions(),{'q1':'A','q2':'坏答案','q3':18},True)

def test_partial_path_next():
    assert walk(questions(),{'q1':'A'})['next_question']['id']=='q3'

def test_invalid_target():
    q=questions();q[0]['rules'][0]['target']='missing'
    assert not inspect_rules(q)['valid']

def test_backward_jump():
    q=questions();q[0]['rules'][0]['target']='q1'
    assert not inspect_rules(q)['valid']

def test_duplicate_ids():
    q=questions();q[1]['id']='q1';assert not inspect_rules(q)['valid']

def test_empty_survey():assert not inspect_rules([])['valid']

@pytest.mark.parametrize('value',[True,'18',18.5,-1,121,float('nan'),float('inf'),{},[],10**400,10**20])
def test_numeric_invalid(value):
    with pytest.raises(AnswerError):validate_answer(questions()[2],value)

@pytest.mark.parametrize('value',[0,18,120])
def test_numeric_boundaries(value):assert validate_answer(questions()[2],value)==value

@pytest.mark.parametrize('value',['a','abcde','  ',12])
def test_text_invalid(value):
    with pytest.raises(AnswerError):validate_answer(questions()[1],value)

def test_optional_null():
    q=questions()[1];q['required']=False
    assert validate_answer(q,None) is None

def test_multiple_rules_first_match():
    q=questions();q[0].update(type='multiple',rules=[{'op':'contains','value':'A','target':'q3'},{'op':'contains_all','value':['A','B'],'target':'END'}])
    r=walk(q,{'q1':['A','B'],'q3':10},True)
    assert r['trace'][0]['target']=='q3'
    assert inspect_rules(q)['warnings']

def test_numeric_end_branch():
    q=questions()[2:];q[0]['rules']=[{'op':'between','value':[18,30],'target':'END'}]
    assert walk(q,{'q3':18},True)['trace'][0]['target']=='END'

def test_multiple_count_and_duplicate():
    q=questions()[0];q.update(type='multiple',validation={'min_choices':2,'max_choices':2},rules=[])
    for v in [['A'],['A','A'],['A','C']]:
        with pytest.raises(AnswerError):validate_answer(q,v)
    assert validate_answer(q,['A','B'])==['A','B']

def test_bad_range():
    q=questions();q[2]['validation']={'min_value':100,'max_value':10}
    assert not inspect_rules(q)['valid']

def test_type_mismatch_rule():
    q=questions();q[0]['rules'][0]['op']='gt'
    assert not inspect_rules(q)['valid']

def test_unknown_answer():
    with pytest.raises(AnswerError):walk(questions(),{'q99':'x'})

def test_impossible_integer():
    q=questions();q[2]['validation']={'integer':True,'min_value':0.1,'max_value':0.9}
    assert not inspect_rules(q)['valid']

@pytest.mark.parametrize('op,value,answer,hit',[
    ('eq',5,5,True),('gt',5,5,False),('gt',5,6,True),
    ('gte',5,5,True),('lt',5,5,False),('lt',5,4,True),
    ('lte',5,5,True),('between',[3,5],5,True),('between',[3,5],6,False),
])
def test_all_numeric_operators(op,value,answer,hit):
    q=questions()[2:];q[0]['rules']=[{'op':op,'value':value,'target':'END'}]
    r=walk(q,{'q3':answer},True)
    assert bool(r['trace']) is hit

def test_multiple_contains_all():
    q=questions()[0];q.update(type='multiple',rules=[{'op':'contains_all','value':['A','B'],'target':'END'}])
    assert walk([q],{'q1':['A','B']},True)['trace']
    assert not walk([q],{'q1':['A']},True)['trace']

def test_duplicate_options_blocked():
    q=questions();q[0]['options']=['A','A'];assert not inspect_rules(q)['valid']

def test_irrelevant_limits_blocked():
    q=questions();q[0]['validation']={'min_length':2};assert not inspect_rules(q)['valid']

