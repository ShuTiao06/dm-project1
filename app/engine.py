"""Pure stage-one rules: ordered, forward-only branching with server validation."""
import math
from numbers import Real


class AnswerError(ValueError):
    def __init__(self, question_id, message):
        self.question_id = question_id
        super().__init__(message)


def numeric(v):
    try:
        return isinstance(v, Real) and not isinstance(v, bool) and math.isfinite(v) and abs(v) <= 9007199254740991
    except (OverflowError, TypeError):
        return False


def inspect_rules(questions):
    errors, warnings = [], []
    if not questions:
        errors.append('问卷至少需要一道题')
    ids = [q['id'] for q in questions]
    if len(set(ids)) != len(ids):
        errors.append('题目 ID 必须唯一')
    for i, q in enumerate(questions):
        prefix = q['id'] + ': '
        options, kind = q.get('options', []), q['type']
        limits = q.get('validation', {})
        if kind in ('single', 'multiple'):
            if len(options) < 2 or len(set(options)) != len(options) or any(not x.strip() or len(x)>200 for x in options):
                errors.append(prefix + '选择题至少两个不重复且非空的选项，每项不超过200字')
        elif options:
            errors.append(prefix + '填空题不能设置选项')
        for lo, hi in [('min_choices', 'max_choices'), ('min_length', 'max_length'), ('min_value', 'max_value')]:
            if limits.get(lo) is not None and limits.get(hi) is not None and limits[lo] > limits[hi]:
                errors.append(prefix + lo + ' 不能大于 ' + hi)
        allowed = {'single': set(), 'multiple': {'min_choices','max_choices'}, 'text': {'min_length','max_length'}, 'number': {'min_value','max_value','integer'}}[kind]
        for key, val in limits.items():
            if val is not None and val is not False and key not in allowed:
                errors.append(prefix + '该题型不能使用约束 ' + key)
        if kind == 'multiple':
            if any(limits.get(k) is not None and limits[k] > len(options) for k in ['min_choices','max_choices']):
                errors.append(prefix + '选择数量不能超过选项数')
            if q['required'] and limits.get('max_choices') == 0:
                errors.append(prefix + '必答多选题最多不能为0')
        if kind == 'number' and limits.get('integer'):
            lo, hi = limits.get('min_value'), limits.get('max_value')
            if lo is not None and hi is not None and math.ceil(lo) > math.floor(hi):
                errors.append(prefix + '整数范围内没有合法整数')
        if kind == 'number' and any(limits.get(k) is not None and not numeric(limits[k]) for k in ['min_value','max_value']):
            errors.append(prefix + '数值约束须位于 ±9007199254740991 内，避免跨语言精度损失')
        seen = set()
        if len(q.get('rules', [])) > 1:
            warnings.append(prefix + '多条规则按顺序匹配，第一条命中生效，请检查重叠条件')
        for rule in q.get('rules', []):
            target, op, value = rule['target'], rule['op'], rule['value']
            if target != 'END' and (target not in ids or ids.index(target) <= i):
                errors.append(prefix + '跳转目标必须为后续题目或 END（不允许回跳和循环）')
            valid = False
            if kind == 'single':
                valid = op == 'eq' and isinstance(value, str) and value in options
            elif kind == 'multiple':
                valid = (op == 'contains' and isinstance(value,str) and value in options) or (op == 'contains_all' and isinstance(value,list) and len(value)>0 and all(isinstance(v,str) and v in options for v in value) and len(set(value))==len(value))
            elif kind == 'number':
                valid = (op in ('eq','gt','gte','lt','lte') and numeric(value)) or (op == 'between' and isinstance(value,list) and len(value)==2 and all(numeric(v) for v in value) and value[0]<=value[1])
            if not valid:
                errors.append(prefix + '规则操作符或比较值与题型不匹配')
            sig = repr((op,value))
            if sig in seen:
                warnings.append(prefix + '存在重复条件，后面的相同条件不会生效')
            seen.add(sig)
    return {'valid': not errors, 'errors': errors, 'warnings': warnings, 'question_count': len(questions)}


def validate_answer(q, value):
    if value is None or value == '' or value == []:
        if q['required']:
            raise AnswerError(q['id'], '这道题为必答题')
        return None
    kind, lim = q['type'], q.get('validation', {})
    def fail(message):
        raise AnswerError(q['id'], message)
    if kind == 'single':
        if not isinstance(value,str) or value not in q['options']:
            fail('请选择一个合法选项')
    elif kind == 'multiple':
        if not isinstance(value,list) or not all(isinstance(v,str) and v in q['options'] for v in value):
            fail('多选答案必须是合法选项数组')
        if len(set(value)) != len(value):
            fail('不能重复选择同一选项')
        for key, compare, msg in [('min_choices', lambda a,b:a<b, '选择数量不足'), ('max_choices', lambda a,b:a>b, '选择数量过多')]:
            if lim.get(key) is not None and compare(len(value),lim[key]): fail(msg)
    elif kind == 'text':
        if not isinstance(value,str): fail('请输入文本')
        if not value.strip() and q['required']: fail('必答文本不能仅含空白')
        if len(value)>10000: fail('文本不能超过10000字')
        if lim.get('min_length') is not None and len(value)<lim['min_length']: fail('文本长度不足')
        if lim.get('max_length') is not None and len(value)>lim['max_length']: fail('文本过长')
    elif kind == 'number':
        if not numeric(value): fail('请输入 ±9007199254740991 内的有限数字，不能用字符串或布尔值代替')
        if lim.get('integer') and int(value)!=value: fail('必须是整数')
        if lim.get('min_value') is not None and value<lim['min_value']: fail('数字小于最小值')
        if lim.get('max_value') is not None and value>lim['max_value']: fail('数字大于最大值')
    return value


def matches(rule, value):
    if value is None: return False
    op, v = rule['op'], rule['value']
    if op == 'eq': return value == v
    if op == 'contains': return v in value
    if op == 'contains_all': return all(x in value for x in v)
    if op == 'gt': return value > v
    if op == 'gte': return value >= v
    if op == 'lt': return value < v
    if op == 'lte': return value <= v
    if op == 'between': return v[0] <= value <= v[1]
    return False


def walk(questions, answers, complete=False):
    ids = [q['id'] for q in questions]
    if set(answers)-set(ids): raise AnswerError('_', '答案包含不存在的题目')
    path, cleaned, trace = [], {}, []
    index = 0
    while index < len(questions):
        q = questions[index]
        path.append(q['id'])
        if q['id'] not in answers and not complete:
            return {'path': path, 'answers': cleaned, 'trace': trace, 'next_question': q, 'complete': False}
        value = validate_answer(q, answers.get(q['id']))
        if value is not None: cleaned[q['id']] = value
        target = None
        for ri, rule in enumerate(q.get('rules', [])):
            if matches(rule,value):
                target = rule['target']
                trace.append({'question_id':q['id'], 'rule_index':ri, 'target':target})
                break
        if target == 'END': break
        index = ids.index(target) if target else index+1
    # Reject stale hidden answers rather than count or store them.
    if set(answers)-set(path): raise AnswerError('_', '答案包含已跳过的题目，请重新核对答题路径')
    return {'path':path, 'answers':cleaned, 'trace':trace, 'next_question':None, 'complete':True}
