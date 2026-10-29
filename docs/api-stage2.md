# 第二阶段新增API

所有新增接口有/api前缀，均要求登录Cookie。第一阶段接口保留，完整当前规范见openapi.json。无权/不存在404，输入422，修订或状态冲突409，全局统计越权403。

| 方法与路径 | 用途 |
|---|---|
| GET /library/questions?scope=all或owned或shared&skip=0&limit=50 | 可用题目，limit上限100 |
| POST /library/questions | 创建逻辑题和v1 |
| GET /library/questions/{rid} | 全部版本与来源 |
| POST /library/questions/{rid}/versions | 明确父版本的新版本，仅所有者 |
| POST /library/questions/{rid}/versions/{vid}/restore | 旧版恢复为新版本 |
| POST /library/versions/{vid}/fork | 已授权题复制为自己的逻辑题 |
| GET/POST /library/questions/{rid}/shares | 共享名单/按用户名授权 |
| DELETE /library/questions/{rid}/shares/{uid} | 撤销未来取用 |
| POST /surveys/{sid}/import-question?revision=N | 确切版本导入草稿 |
| POST /surveys/{sid}/questions/{qid}/save-to-library | 本卷题另存副本，不追溯关联历史 |
| GET /library/questions/{rid}/usage?version_id=可选 | 反向使用关系，其他作者标题隐藏 |
| GET /library/questions/{rid}/stats?scope=mine或all&version_id=可选&skip=0&limit=100 | 跨卷版本统计，limit上限1000 |
| GET/POST /banks | 题库列表/创建 |
| PUT /banks/{bid}?revision=N | 修改名称说明，乐观锁 |
| DELETE /banks/{bid} | 软归档，保留版本和问卷 |
| GET/POST /banks/{bid}/items | 条目列表/添加或更新选定版本 |
| DELETE /banks/{bid}/items/{rid} | 从题库移出 |

## 创建与改版

创建请求：
```json
{"definition":{"title":"你的年龄（岁）","type":"number","required":true,"options":[],"validation":{"integer":true,"min_value":0,"max_value":120}},"note":"初始版本"}
```

201返回root与version，包括id、owner_id、root_id、number、definition、fingerprint、parent_version_id、note与时间。改版在请求中增加parent_version_id，成功返回独立版本；父版本必须属于当前root。恢复无请求体，返回新版本和restored_from_version_id。

共享请求 `{"username":"已注册用户名"}`，重复授权幂等。共享涵盖已有和未来版本，不授权改版、恢复或转授权；可fork为自己的独立题。

## 导入

请求 `{"version_id":"确切版本ID","local_id":"age"}`，成功201返回revision+1完整草稿。题目source由服务器绑定，rules为空，本卷可单独配置规则。发布后导入409；无权版本404；重复本地题号、修订冲突、超100题409。常规PUT保存引用题仍校对source与definition，解除source则成为本地题。

## 统计

响应含root_id、scope、grouping=exact_version、versions数组、notice。每版本包含version_id/number/fingerprint/definition/answered/survey_count；选择题options计数；填空题分页values及own_values_count；数字另有average/min/max，无值为null。scope=mine默认；all仅所有者，values仍只含自己问卷，values_scope=own_surveys。不同版本不混算，limit不改变均值或总数。

## 题库

创建/修改请求 `{"name":"校园题库","description":"常用调研题"}`。条目请求 `{"version_id":"版本ID"}`，同逻辑题只保留一个选定版本。列表返回available/version/has_update/latest_version_id；撤销共享后条目保留但available=false。题库不额外授予题目访问权，也不改变已有问卷。
