# 第一阶段 MongoDB 数据库设计

## 设计结论

采用 `users`、`sessions`、`surveys`、`responses` 四个集合。问卷中的题目、约束、规则嵌入问卷文档；不断增长的回答独立存储，通过 `survey_id` 引用问卷。数据库名默认 `dm_project1`，结构版本 `schema_version=1`。启动时由 `app/database.py` 创建 BSON 校验器与索引，其代码即为可执行 schema。

这不是将关系数据库的每张表原样搬进 MongoDB。题目、选项、校验与规则构成一个有界、共同读取的问卷聚合，适合嵌入；回答数量无界且独立追加，不适合嵌入同一问卷。一次读取即可得到完整答题定义，避免按题拼接。每卷最多100题、每题最多100选项、每题最多50规则，避免问卷文档无约束膨胀。

关系数据库也能实现该业务，但可变题型及多态校验需要更多子表/关联或额外 JSON 字段。MongoDB 的嵌入文档、数组和聚合管道与本项目访问方式契合；本系统仍显式实现校验、身份检查和唯一约束，不把“灵活 schema”理解为不做设计。

## 集合字段

| 集合 | 主要字段与 BSON 类型 | 访问与生命周期 |
|---|---|---|
| users | `_id:ObjectId`, `username:string`, `password_hash:string`, `created_at:date` | 注册写入、登录按用户名查；不存明文密码 |
| sessions | `_id:ObjectId`, `token_hash:string`, `user_id:ObjectId`, `expires_at:date` | 随机会话凭证只在 Cookie 中出现，库中保存 SHA-256；到期 TTL 清理 |
| surveys | `_id:ObjectId`, `owner_id:ObjectId`, `title:string`, `description:string`, `allow_anonymous:bool`, `allow_multiple:bool`, `deadline:date/null`, `status:string`, `schema_version:int`, `revision:int`, `questions:array`, 时间字段, `submission_seq:int` | 作者列表、读取问卷、草稿乐观并发更新；发布后内容冻结 |
| responses | `_id:ObjectId`, `survey_id:ObjectId`, `survey_revision:int`, `respondent_key:string`, `request_id:string`, `anonymous:bool`, `user_id:ObjectId?`, `single_key:string?`, `answers:object`, `path:array`, `trace:array`, `submitted_at:date` | 每次有效提交一文档，独立追加、按问卷统计与分页 |

问卷 `revision` 是草稿编辑修订号，不是第二阶段的“题目版本管理”。发布后该修订号不再变化，每份回答引用这个修订号。`schema_version` 用于未来结构迁移时区分格式。

## 问卷样例

以下为 Extended JSON 示意，实际由 PyMongo 写入 ObjectId 与 BSON Date，不把日期当普通字符串保存。

```json
{
  "_id": {"$oid": "000000000000000000000001"},
  "owner_id": {"$oid": "000000000000000000000002"},
  "schema_version": 1,
  "revision": 3,
  "title": "校园学习体验调研",
  "description": "调查自习室使用情况",
  "allow_anonymous": true,
  "allow_multiple": false,
  "deadline": {"$date": "2026-10-30T15:00:00Z"},
  "status": "published",
  "questions": [
    {"id":"q1","title":"是否使用自习室","type":"single","required":true,
     "options":["使用","不使用"],"validation":{},
     "rules":[{"op":"eq","value":"不使用","target":"END"}]},
    {"id":"q2","title":"每周几次","type":"number","required":true,
     "options":[],"validation":{"integer":true,"min_value":0,"max_value":30},"rules":[]}
  ],
  "created_at": {"$date":"2026-10-22T14:00:00Z"},
  "submission_seq": 0
}
```

第一阶段题目 ID 在同一问卷内唯一；不是跨问卷的共享题 ID。用 `q1` 等稳定标识跳转，而不是“当前第几题”的下标，重排不会让目标静默变成另一道题；重排后若构成回跳，体检会阻止发布。

## 回答样例

```json
{
  "survey_id": {"$oid":"000000000000000000000001"},
  "survey_revision":3,
  "respondent_key":"sha256(survey_id:user_id)",
  "single_key":"仅单次填写问卷会保存此字段",
  "request_id":"客户端为一次提交生成的随机UUID",
  "anonymous":true,
  "answers":{"q1":"不使用"},
  "path":["q1"],
  "trace":[{"question_id":"q1","rule_index":0,"target":"END"}],
  "submitted_at":{"$date":"2026-10-22T14:10:00Z"}
}
```

匿名回答不保存 `user_id`，作者 API 也不返回 `respondent_key`、`single_key`、`request_id`。内部散列用于同账号去重，并不构成面对数据库管理员的密码学匿名：管理员掌握用户 ID 可以重算该散列。这里实现的是作业要求中的“对问卷作者匿名”。未匿名时保存 `user_id` 供作者识别账号标识。

`answers` 使用题号到值的映射，单选/文本为 string，多选为 string array，数字为 BSON 数字；未作答的选答题不写入答案对象，已跳过的题也不写入。`path` 记录实际访问题目，`trace` 记录首个命中规则及目标。这些有限冗余用于审计与解释，不另存一份可能失同步的统计汇总。

## 索引设计

| 集合/索引 | 键 | 作用与代价 |
|---|---|---|
| users / uq_username | username，unique | 并发注册也不能重名；每次用户写入维护一个索引 |
| sessions / uq_session_token | token_hash，unique | 会话查找，不在库中保存可直接使用的 token |
| sessions / ttl_session | expires_at，TTL=0 | 自动清理过期会话；TTL 有延迟，鉴权仍显式检查时间 |
| surveys / owner_recent | owner_id ASC, created_at DESC | 作者问卷列表的过滤与倒序分页 |
| surveys / status_deadline | status ASC, deadline ASC | 为状态与截止时间巡检保留；目前分享页仍用 _id 主键 |
| responses / survey_time | survey_id ASC, submitted_at DESC | 问卷回答记录按提交时间分页，也支持按问卷筛选统计 |
| responses / uq_idempotency | survey_id, respondent_key, request_id，unique | 同一账号的一次请求重试不会保存第二份 |
| responses / uq_single_response | survey_id, single_key，partial unique | 只索引包含 string single_key 的文档，实现每人一次；多次填写不受此唯一约束 |

MongoDB 自带的 `_id` 唯一索引仍保留。回答统计先 `$match survey_id`，单选用 `$group`，多选先 `$unwind` 再 `$group`，数字用 `$avg/$min/$max`。不为每个动态题号创建索引，以免索引数量随问卷增长。文本内容分页读取；均值聚合不受分页限制。

## 校验与一致性边界

三层校验分别是：Pydantic 接口结构校验、规则引擎业务校验、MongoDB `$jsonSchema` 核心类型校验。数据库校验器不穷举每个嵌套约束；跨字段约束、ID唯一与规则语义由发布体检负责。直接以数据库管理员身份修改文档可绕过应用业务限制，不属于公开 API 支持的操作。

草稿保存用 `_id + owner_id + status=draft + revision` 做原子条件更新，`revision + 1`；避免两个编辑页静默覆盖。发布也比较读取到的 revision，避免体检后被其他保存替换。发布后不再允许修改题目、规则、匿名和重复填写设置，以保证历史统计语义稳定。

关闭与提交通过对同一 survey 文档的原子状态检查明确先后：提交在状态为 published 且未截止时原子获得准入，再插入 response。若关闭先发生，准入失败；若准入先发生，该回答允许在关闭动作之后完成写入。截止判断同样以准入点为准，不保证网络响应一定在截止时间前送达。

本机 MongoDB 单节点不依赖多文档事务。准入后进程崩溃可能使 `submission_seq` 增长而没有 response，因此该值只表示准入尝试，不作为回答总数。实际统计只计算持久化的 responses。唯一索引保证并发重复提交不会生成两份有效记录。项目未声称跨文档强事务或断电情况下的恰好一次执行。

## 参考资料

- MongoDB 官方 Unique Indexes：https://www.mongodb.com/docs/manual/core/index-unique/
- FastAPI 官方 Lifespan Events：https://fastapi.tiangolo.com/advanced/events/

资料用于核对索引约束与连接生命周期；实际行为以项目代码和真实集成测试为准。
