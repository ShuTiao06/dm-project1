# 第二阶段数据库演化设计

## 保留与新增

保留users、sessions、surveys、responses四集合及原规则引擎。新增五个业务集合，另有migrations记录升级标识。问卷定义仍内嵌，回答仍独立追加，没有推倒重做。

surveys.schema_version允许1和2；新建/保存草稿标记2，旧文档不批量改写。Question新增可选source，含字符串root_id、version_id、fingerprint。旧题目没有source也正常填写与统计，不按标题自动合并。

| 新集合 | 关键字段 | 用途 |
|---|---|---|
| question_roots | owner_id, next_version, created_at, derived_from_version_id? | 逻辑题身份与所有者，复制共享题记录来源 |
| question_versions | root_id, number, definition, fingerprint, parent_version_id, restored_from_version_id?, note, created_at | 不可变定义，父版本形成分支，恢复生成新文档 |
| question_shares | root_id, grantee_id, created_at | 全部版本取用授权，不授予修改和看其他作者明细的权利 |
| question_banks | owner_id, name, description, revision, archived, created_at | 个人题库，乐观锁编辑，软归档 |
| bank_items | bank_id, root_id, version_id, updated_at | 每个题库对一逻辑题选定一版本，显式更新 |

definition保存title/type/required/options/validation，复用旧题型与约束。题号与rules属于问卷上下文，不保存在题库中；导入后可以用不同本地题号和跳转配置。

## 不可变版本与快照

definition标准化后排序JSON并生成SHA-256指纹。导入检查授权；保存引用题时检查root/version归属、source和题目内容一致性，伪造引用或修改题目还声称旧版本会422，避免污染跨卷统计。需要改题则创建版本、复制自己的题，或解除引用成为本地题。

问卷仍持有完整快照，所有填写与单卷统计以快照为准。改版、恢复、题库更新不回写问卷；原发布冻结继续有效。撤销共享只阻止未来取用，同一草稿原题号已有快照可继续保存，已发布仍可填；新增实例或跨卷复制仍查权限。

接口不可变不抵抗数据库管理员绕过应用直接改库；指纹不是签名。版本计数用root原子$inc，并发不重复，分配后失败可出现空号；最新版本从成功落库的版本倒序查，不依赖冗余head。root/v1初建非多文档事务，故障可能留下无版本root，列表不会展示，需维护检查。不宣称跨文档强事务。

## 索引

保留第一阶段所有索引。新增root(owner_id,created_at)；versions(root_id,number)唯一和parent_version_id；shares(root_id,grantee_id)唯一及(grantee_id,created_at)；banks(owner_id,archived)；items(bank_id,root_id)唯一；surveys.questions.source.root_id/version_id多键索引。初始化建立核心BSON校验器，可执行定义见app/database.py，导出见schema/mongodb-schema.json。

## 统计与权限

从surveys按source.root_id过滤、展开questions并匹配确切version_id，用$lookup按survey_id关联responses；将answers转成键值数组匹配本地题号，仅保留有效值。单选分组、多选展开分组、数字avg/min/max，明细分页。旧问卷无来源不参与跨卷统计，不偷偷改变历史含义。

scope=mine默认只看本人问卷；题目所有者可scope=all查看所有引用卷的聚合。其他作者原始填空明细不返回。小样本聚合仍可能推断个别数值，不声称统计匿名化。usage对别人的问卷隐藏标题，只有关联ID、状态、版本；共享不能变成绕过问卷作者权限的入口。

不同确切版本独立组，即使恢复版内容指纹相同也不混合。一次回答在同卷两题实例中各作答，则贡献两次观察值；不是去重人数。这样保留修改前后差异，避免单位或选项语义改变时无条件合并。

版本和条目独立增长，避免无界历史数组。跨卷查询实时聚合，未做物化汇总或大规模性能压测；填写热路径仍只读survey快照，无需逐题读取版本库。
