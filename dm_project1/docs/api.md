# 第一阶段 API 说明

基础地址：`http://127.0.0.1:8000`。请求与响应为 JSON；静态页面另行提供。成功登录后以 HttpOnly `session` Cookie 鉴权，浏览器自动携带，Python 客户端使用同一个 `httpx.Client` 保存 Cookie。不需要自行构造 Authorization 头。

## 接口一览

| 方法 | 路径 | 权限 | 行为 |
|---|---|---|---|
| GET | /api/health | 无 | MongoDB ping、当前库名、结构版本 |
| POST | /api/auth/register | 无 | 注册，成功201 |
| POST | /api/auth/login | 无 | 登录并设置会话Cookie |
| POST | /api/auth/logout | 当前Cookie | 删除本次会话并清除Cookie |
| GET | /api/auth/me | 登录 | 当前用户（不含密码散列） |
| GET | /api/surveys | 登录 | 自己的问卷列表，skip=0，limit=50，上限100 |
| POST | /api/surveys | 登录 | 创建草稿，成功201 |
| GET | /api/surveys/{sid} | 作者 | 完整问卷设计 |
| PUT | /api/surveys/{sid}?revision=N | 作者 | 以指定修订号整体更新草稿 |
| POST | /api/surveys/{sid}/questions?revision=N | 作者 | 向草稿添加一道题 |
| POST | /api/surveys/{sid}/check | 作者 | 发布前体检；返回valid/errors/warnings |
| POST | /api/surveys/{sid}/publish | 作者 | 自动体检并发布，返回分享URL |
| POST | /api/surveys/{sid}/close | 作者 | 从published进入closed |
| GET | /api/public/surveys/{sid} | 登录 | 获取已发布或已关闭问卷，返回accepting |
| POST | /api/public/surveys/{sid}/next | 登录 | 根据部分答案返回下一题或完成状态 |
| POST | /api/public/surveys/{sid}/responses | 登录 | 重算完整路径并保存提交，成功201 |
| GET | /api/surveys/{sid}/stats | 作者 | 整卷/单题统计，question_id可选；skip=0，limit=100，上限1000 |
| GET | /api/surveys/{sid}/responses | 作者 | 回答分页，skip=0，limit=50，上限100；隐藏内部去重字段 |
| GET | / | 无 | 工作台网页；未登录显示登录表单 |
| GET | /survey/{sid} | 无 | 分享页面，填写前引导登录 |
| GET | /docs | 无 | Swagger UI，需要外部资源网络可用 |
| GET | /openapi.json | 无 | 机器可读 OpenAPI 规范 |

`public` 是填写端 API 命名空间，并不代表允许未登录填写。若 sid 非合法 ObjectId，返回404。

## 注册与登录

```json
{"username":"student_a","password":"YourOwnPassword123"}
```

注册返回用户 id、username、created_at；登录返回同样的公开资料，并通过 Set-Cookie 建立会话。用户名重复409，密码错误401，参数结构错误422。用户名区分大小写。

## 创建问卷

```json
{
  "title":"学习体验调研",
  "description":"请根据实际情况填写",
  "allow_anonymous":true,
  "allow_multiple":false,
  "deadline":"2026-10-30T23:00:00+08:00",
  "questions":[
    {"id":"q1","title":"是否参加活动","type":"single","required":true,
     "options":["参加","不参加"],"validation":{},
     "rules":[{"op":"eq","value":"不参加","target":"q3"}]},
    {"id":"q2","title":"选择偏好的形式","type":"multiple","required":true,
     "options":["线上","线下","混合"],"validation":{"min_choices":1,"max_choices":2},"rules":[]},
    {"id":"q3","title":"年龄","type":"number","required":true,
     "options":[],"validation":{"min_value":0,"max_value":120,"integer":true},
     "rules":[{"op":"gte","value":60,"target":"END"}]},
    {"id":"q4","title":"建议","type":"text","required":false,
     "options":[],"validation":{"min_length":2,"max_length":200},"rules":[]}
  ]
}
```

成功201返回完整草稿，包含 `id`、`owner_id`、`status=draft`、`revision=1`、`schema_version=1`。只提供 title 也可创建空草稿，但空草稿不能发布。创建阶段允许暂存规则语义错误，由 check 提示；模型结构错误直接422。

更新草稿的请求体与创建一致，不要提交 id、owner_id、status 等服务端字段。revision 参数必须与读取值一致；成功后 revision 增加1。添加题目的请求体是上述 questions 数组中的单个对象。

截止时间必须带时区，null表示不限时。后端统一以 UTC 比较与存储。题号须满足 `^[a-zA-Z][a-zA-Z0-9_]{0,39}$`，防止将点号或美元符号作为动态数据库字段；最多100题。

## 规则体检与发布

`POST /api/surveys/{sid}/check` 无请求体，正常返回200：

```json
{"valid":false,"errors":["q1: 跳转目标必须为后续题目或 END（不允许回跳和循环）"],"warnings":[],"question_count":4}
```

体检不通过时 publish 返回422，detail中包含同一体检对象。通过后返回200：

```json
{"survey":{"id":"问卷ID","status":"published"},"url":"/survey/问卷ID","preflight":{"valid":true,"errors":[],"warnings":[],"question_count":4}}
```

这里的 survey 实际包含完整问卷，示例仅保留关键字段。发布后冻结整个定义，不允许修改截止时间、匿名开关或题目。关闭时无请求体，成功返回状态为closed的问卷。关闭不删除回答。

## 下一题

```json
{"answers":{"q1":"不参加"}}
```

返回：

```json
{
  "path":["q1","q3"],
  "answers":{"q1":"不参加"},
  "trace":[{"question_id":"q1","rule_index":0,"target":"q3"}],
  "next_question":{"id":"q3","title":"年龄","type":"number"},
  "complete":false
}
```

next_question 实际包含完整题目定义。若所有到达问题都有答案或已跳至END，则 next_question=null、complete=true。选答题不回答时显式传该题为null才能表示已跳过；不传键表示尚未处理该题。

## 提交

```json
{
  "answers":{"q1":"不参加","q3":21,"q4":"增加实践活动"},
  "anonymous":true,
  "request_id":"d846827c-16fd-4879-9842-4375fd2aa9d8"
}
```

request_id 为8–80位字母/数字/下划线/连字符。为每次新的填写生成新值，网络重试使用原值。

首次保存返回201：`{"id":"回答ID","replayed":false,"path":["q1","q3","q4"]}`。同一账号同一request_id重试返回201和同一id、replayed=true，不新增回答。该幂等键识别一次操作，不能借相同键修改既有提交。

答案校验错误返回422，例如 `{"detail":"必须是整数","question_id":"q3"}`。问卷关闭、截止或禁止多次填写时返回409。匿名不允许时返回422。必答只检查实际到达路径；包含未知题或跳过题答案会被拒绝。

数值限定为有限 JSON number，绝对值不超过9007199254740991，使浏览器整数精度和数据库存储边界一致。数字字符串和布尔值不能代替数字。文本以Unicode码点计长。

## 统计与回答

`GET /api/surveys/{sid}/stats?question_id=q3&skip=0&limit=100`

```json
{
  "survey_id":"问卷ID",
  "title":"学习体验调研",
  "total_responses":2,
  "questions":[{"question_id":"q3","title":"年龄","type":"number","answered":2,
    "values":[20,40],"skip":0,"limit":100,"average":30.0,"min":20,"max":40}]
}
```

单选/多选返回 `options:[{"label":"选项","count":1}]`；文本返回 values；数字额外返回average/min/max。空数字集合均为null。分页只影响填空 values，不影响回答数和均值。若 question_id 不存在，返回404。不提供 question_id 则返回全部题目统计。

回答记录只对作者开放；匿名记录不包含user_id，任何记录均不返回respondent_key、single_key、request_id。记录含 answers/path/trace，可审计回答路径与规则命中。

## 错误与安全

| 状态码 | 含义 |
|---|---|
| 401 | 未登录、会话过期、密码错误 |
| 403 | Origin与站点不一致的跨站写入 |
| 404 | 不存在、未发布、非作者访问管理资源 |
| 409 | 状态冲突、修订号冲突、禁止重复、用户名重复、关闭/截止 |
| 413 | 声明的请求体超过1MB |
| 422 | 输入结构、答案、规则或发布体检错误 |
| 503 | MongoDB服务暂不可用 |

不开放跨域凭据访问；网页同源请求，服务端检查写操作Origin，Cookie防脚本读取。`/docs` 仅为课程接口探索工具，业务网页脚本与样式均本地提供。新客户端最好先访问health，再使用同一个Cookie会话完成流程。
