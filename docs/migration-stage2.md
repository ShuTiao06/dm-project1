# 第二阶段迁移与兼容说明

## 第一阶段基线

第一阶段四集合、嵌入题目、独立回答、路径引擎、API与测试作为基线保留。snapshots/stage1_baseline.zip和清单未覆盖，verify_stage1_archive.py已实际校验通过。

本次拉取同一仓库main的第一阶段提交6021ad4cbe7261060658c62a627ac3acc30ec7a3，与E盘main/database/engine/models/app.js做文本比较均一致（Git工作树换行差异不作为语义变更）。第二阶段在此基础增量修改，engine.py和原app.js不改动，新增catalog模块和扩展网页脚本，不另起问卷实现。

## 原设计与新问题

题目原本只在问卷内，不能跨卷识别同一道题，也没有授权与版本历史。仅新增一个共享question_id并让所有问卷实时引用“最新题”会破坏旧问卷与回答语义，因此不能简单替换嵌入方式。

本次保留原快照读取路径，在库外新增逻辑题和不可变版本，导入时增加可校验来源。新建、改版和恢复只追加版本，不回写问卷；原题型、约束、跳转和单卷统计继续复用。

## 升级方式

1. 停止对原库的应用写入，避免跨集合备份期间产生不一致；TTL会话清理可能继续发生。
2. 执行python scripts/upgrade.py只做预览。MONGODB_URI和MONGODB_DB与原系统一致。
3. 执行python scripts/upgrade.py --apply --backup-dir private_backup/before_stage2_20261028，目录必须不存在。
4. 工具导出每集合原始BSON、索引/选项及SHA-256清单，再幂等新增五集合、索引和schema_version允许值1/2；不重写旧文档。users/surveys/responses计数校验保持，会话因TTL不作静态计数承诺。
5. 新版启动连接原库，旧用户继续登录，旧问卷继续填和单卷统计，新建题库为空，按需创建/导入。

备份不是MongoDB副本集一致性快照，需要停写。本机独立服务器方案不依赖多文档事务；备份恢复工具已做真实数据库测试，但没有演练断电恢复或生产级RPO/RTO。

## 兼容策略

旧问卷没有source也不补填，不把相同标题合并。将旧题保存为常用题是新副本，不追溯旧回答。如果需要让新问卷参与跨卷统计，显式导入确定题目版本。旧问卷回答结构不变，通过固定survey快照获取来源，无需批量迁移responses。

schema_version2只用于新建/保存问卷，数据库接受1/2。共享撤销不删除旧快照；已发布定义依旧不可编辑。所有原73项测试不改动并通过，新增测试覆盖旧格式文档在连续两次initialize前后内容和已有回答完全一致。

## 回退

restore_backup.py先验证所有BSON哈希，再恢复到不同名称的新空库。拒绝原库名与非空目标，避免清空或覆盖。示例：python scripts/restore_backup.py private_backup/before_stage2_20261028 --target-db dm_project1_restore。之后使用第一阶段归档代码，设置MONGODB_DB=dm_project1_restore运行。

不要用旧版initialize直接对第二阶段新数据运行，因为旧验证器只接受schema_version1。新增数据库和旧数据都应先保留，人工确认回退验收后再决定清理，不提供自动删库步骤。

## 尚未做的外部操作

交付包与报告生成不等于已更新远程GitHub或已提交水杉。更新时继续使用同一仓库并保留历史，排除备份与凭据。实际E盘部署和原库升级结果以交付时的deployment记录为准，未执行操作不能写成已完成。
