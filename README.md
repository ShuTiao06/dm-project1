# 问序 SurveyFlow 第二阶段

当代数据管理系统大作业一 · 葛一凡 · 10245501445。基于第一阶段增量扩展，使用FastAPI + PyMongo + MongoDB，网页无需构建。仓库：https://github.com/ShuTiao06/dm-project1

## 第二阶段功能

常用题保存与复用、按用户名共享/撤销、不可变题目版本、历史与来源、任意旧版分支、恢复生成新版本、反向使用查询、题库创建/重命名/归档/条目管理、显式版本更新、跨问卷按确切版本统计。第一阶段四题型、配置跳转、规则体检、截止、提交、单卷统计和防重全部保留。

103项自动测试已在真实MongoDB通过。证据见docs/test-results-stage2.xml、docs/test-run-stage2.txt；不是对其他电脑环境的保证。

## 第二阶段启动与升级

代码内容放到原项目根目录，勿套两层文件夹。MongoDB保持运行。关闭旧项目写入服务后，先备份升级，再启动：

```bat
conda activate dm_project1
cd /d "E:\当代数据管理系统\大作业\dm_project1"
python scripts/upgrade.py
python scripts/upgrade.py --apply --backup-dir private_backup\before_stage2_20261028
python -m uvicorn app.main:app --host 127.0.0.1 --port 8002
```

打开 [http://127.0.0.1:8002](http://127.0.0.1:8002)。已有依赖不用重装，新环境先执行 `python -m pip install -r requirements-lock.txt`。也可用python run.py启动8000端口。正式库默认dm_project1；演示库dm_project1_stage2_demo相互独立。

备份目录必须不存在，如已有同名目录换一个新名称。升级只添加集合、索引和允许的结构版本，不重写旧问卷和回答。启动也会幂等初始化，但已有数据建议先备份。备份含用户数据，不能上传GitHub。

需要恢复时，执行 `python scripts/restore_backup.py private_backup\before_stage2_20261028 --target-db dm_project1_restore`，工具校验全部SHA-256后恢复到不同名称的空数据库，拒绝覆盖原库或非空库。第一阶段回退应使用归档代码与恢复后的数据库，不要将第一阶段初始化器直接用于第二阶段新数据。

## 第二阶段验收

1. 登录后进入“题目与版本”，新建年龄数字题v1；创建一个题库，将v1加入。
2. 创建问卷A和B，各从题库导入同一v1，发布后分别提交20与40。
3. 题目详情中查看跨问卷统计：2次作答、2份问卷、均值30。
4. 基于v1修改生成v2；旧问卷仍用v1。恢复v1生成v3，不覆盖v1/v2。
5. 题库提示新版，手动“采用最新版本”；已有问卷保持原内容。
6. 另一个用户先注册，再按用户名共享。对方可使用/复制，不能修改原题。撤销共享不破坏已有问卷。

导入题的定义锁定，跳转规则仍可在问卷内设置；需要改题应另建版本，或解除引用成为本地题。将旧问卷题“保存到常用题”只是另存副本，不追溯关联旧回答。全局统计仅所有者可看聚合，其他作者原始填空内容不返回；不同版本不混算。

## 当前测试与文档

执行 `python -m pytest -q --junitxml=docs/test-results-local.xml`，包含原73项回归与30项新增用例。测试仅清除自己创建的随机测试库，绝不清空正式库。受限环境可加 `--basetemp=work\pytest-local-1`，指定一个新建临时目录。

| 文档 | 内容 |
|---|---|
| docs/report-stage2.md | 第二阶段项目完成报告 |
| docs/第二阶段项目完成报告.html | 浏览器可读报告 |
| docs/2026_ECNU_PJ1_2_葛一凡.pdf | 水杉提交PDF，开头为同一GitHub链接 |
| docs/database-stage2.md | 数据模型、索引、不可变版本、权限与统计 |
| docs/api-stage2.md | 新增API、请求和返回 |
| docs/testing-stage2.md | 实测输入输出、结果与浏览器证据 |
| docs/migration-stage2.md | 升级、兼容、备份恢复和差异 |
| docs/ai-log-stage2.md | 第二阶段真实AI使用日志 |

第一阶段基线ZIP和清单不变，运行 `python scripts/verify_stage1_archive.py` 验证归档。旧verify_snapshot.py比较工作树与第一阶段，在第二阶段出现预期差异；不应覆盖基线消除差异。

更新到第一阶段同一个GitHub仓库，保留历史，不删除重建。排除private_backup、.bson、.env和缓存。水杉提交2026_ECNU_PJ1_2_葛一凡.pdf，截止2026年10月30日00:00北京时间，即29日晚结束。本地系统未做公网部署、大规模压测或生产级灾难恢复；跨卷作答次数不是独立人数。


第一阶段原始说明保留在docs/README-stage1-original.md与归档ZIP内。
