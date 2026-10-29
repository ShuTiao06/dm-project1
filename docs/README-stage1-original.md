# 问序 SurveyFlow

《当代数据管理系统》大作业一第一阶段。Python FastAPI + PyMongo + 原生 HTML/CSS/JavaScript，所有业务数据存储于 MongoDB。未使用关系数据库，也未使用现成问卷系统框架。

## 三分钟启动

打开 **Anaconda Prompt**，逐行执行：

```bat
conda activate dm_project1
cd /d "E:\当代数据管理系统\大作业\dm_project1"
python run.py
```

看到 `Uvicorn running on http://127.0.0.1:8000` 后，浏览器打开 **http://127.0.0.1:8000**。不要双击 HTML 文件。

首次使用：注册一个用户名（至少3位）和密码（至少8位），登录后点击“体验四题型示例”，点击“规则自动体检”，再点击“发布问卷”。注册不会自动预置用户；本次浏览器验收在当前电脑留下了 `survey_demo_1022` 演示账号和两份回答，项目压缩包不包含数据库数据。

**你的环境已安装依赖，无需先重装。** 若在新电脑运行：

```bat
conda create -n dm_project1 python=3.12 -y
conda activate dm_project1
python -m pip install -r requirements-lock.txt
python run.py
```

`requirements-lock.txt` 是本次实测版本；`requirements.txt` 给出兼容范围。项目不依赖 transformers、huggingface-hub；截图里的相关缺包提示不参与本系统执行。

## 解压放置

压缩包内只有一个 `dm_project1` 根文件夹。解压后把根文件夹**里面的内容**放到 `E:\当代数据管理系统\大作业\dm_project1`，避免出现 `dm_project1\dm_project1\run.py`。原有 `test_mongodb.py` 可以保留。

默认连接 `mongodb://127.0.0.1:27017/`，默认数据库 `dm_project1`。首次启动自动创建4个集合、BSON 校验器和索引。不会清空已有数据库。若同名集合里已有不兼容的数据，建议先改用新的数据库名，保留原数据：

```bat
set MONGODB_DB=dm_project1_stage1
python run.py
```

`.env.example` 是配置说明，**程序不自动读取 .env**。用命令行环境变量配置 `MONGODB_URI`、`MONGODB_DB` 和 `SESSION_HOURS`（默认24）。PowerShell 对应 `$env:MONGODB_DB='dm_project1_stage1'`。

## Spyder 运行

确认 Spyder 控制台使用 `dm_project1` 的解释器。把工作目录设为项目根目录，打开 `run.py`，按 F5。服务器运行时控制台会持续占用，这是正常现象；浏览器里操作网页。停止时在控制台中断执行。如果已有一个服务器运行，勿再次 F5；否则会报告端口占用。

若 Spyder 的交互事件循环报 `asyncio.run() cannot be called from a running event loop`，直接使用上面的 Anaconda Prompt 启动方式即可。项目不要求依赖 Spyder 才能运行。

## 功能与验收

1. 注册、登录；用户只能管理自己的问卷，作者专属统计与回答记录。
2. 可视化创建草稿，添加、删除、移动题目，编辑约束与条件跳转。
3. 单选、多选、文本、数字；多选精确数量可设最小值=最大值。
4. 单选等于、多选包含/包含全部、数字比较/闭区间；按顺序取首个命中规则，默认进入下一题，支持跳至结束。
5. 发布前自动体检：重复题号、非法选项、错误范围、题型不匹配、失效目标、回跳/循环、整数区间不可满足；提示多规则优先级风险。
6. 发布后冻结内容；截止时间带时区；手动关闭；通过 `/survey/{id}` 分享。
7. 登录后逐题填写，服务端检查路径和输入；被跳过的必答题不要求回答，伪造隐藏答案会被拒绝。
8. 匿名表示不向作者暴露账号，仍需登录；可配置每账号单次或多次填写。唯一索引防并发重复，request_id 使网络重试幂等。
9. MongoDB 实时统计选项次数、回答人数、全部填空内容（分页）、数字均值和极值；可查看整卷或单题。
10. 保留答题路径和规则命中轨迹，支持解释跳转原因；保留独立第一阶段源码与设计快照。

详细的5分钟演示见 [验收步骤](docs/acceptance.md)，输入/预期/实测见 [测试说明](docs/testing.md)。

## 自动化测试

MongoDB 保持运行，在项目根目录执行：

```bat
python -m pytest -q --junitxml=docs/test-results-local.xml
```

测试创建随机的 `dm_project1_test_<uuid>` 数据库，结束后只删除本次随机测试库；不操作正式 `dm_project1` 数据库。连接故障会明确失败，不会降级为内存模拟。

已执行结果和环境见 `docs/testing.md`、`docs/test-results.xml`、`docs/test-run.txt`。请把自己重新执行的结果另存，勿将未经运行的用例写成通过。

## 文档导航

| 文档 | 内容 |
|---|---|
| [项目完成报告](docs/report.md) | 项目目标、设计、创新、测试、问题、AI使用总结 |
| [可打印报告](docs/项目完成报告.html) | 浏览器打开阅读、打印或另存为PDF；提交前填写姓名学号 |
| [数据库设计](docs/database-design.md) | 四集合设计、样例、嵌入/引用取舍、索引和一致性 |
| [API说明](docs/api.md) | 所有接口、权限、请求样例、错误码 |
| [关键逻辑](docs/logic.md) | 规则语义、校验顺序、状态与并发 |
| [测试说明](docs/testing.md) | 真实结果、输入输出、覆盖与限制 |
| [AI使用日志](docs/ai-log.md) | 本次真实提示词、产物、缺陷修复、贡献边界 |
| [未来演化设计](docs/evolution.md) | 第二阶段只作设计，未实现题库、共享、版本管理 |
| [提交清单](docs/submission-checklist.md) | 提交前本地验收和个人信息填写 |

运行后 `http://127.0.0.1:8000/docs` 提供 Swagger UI（页面的外部资源需要联网）；完全离线时可以使用 `docs/api.md` 和 `docs/openapi.json`。`/api/health` 检查数据库连接，`python scripts/inspect_db.py` 查看真实集合计数与索引。

## 第一阶段快照

`snapshots/stage1_baseline.zip` 保存本阶段代码和设计，`stage1_manifest.json` 保存逐文件 SHA-256 与压缩包校验和。执行 `python scripts/verify_snapshot.py` 可检查当前文件与基线是否一致。`snapshot.py` 拒绝覆盖已有快照。后续第二阶段应在当前核心结构上增量演化，不修改已归档快照。

## 常见问题

- `ModuleNotFoundError`：先激活 dm_project1，使用 `python -m pip`，避免依赖装入另一个解释器。
- `ServerSelectionTimeoutError`：检查 MongoDB 服务、地址和端口。启动失败不会退回其他数据库。
- `WinError 10048`：8000端口已有进程。关闭之前的项目服务，或运行 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8001`。
- 登录后仍显示登录页：全程使用同一个地址，勿在 localhost 与 127.0.0.1 之间切换，两者 Cookie 不共享。
- 发布失败：先看体检错误，确保 ID 唯一、规则目标位于后面、截止时间在未来。
- “草稿版本冲突”：另一页面已保存过；返回列表重新打开，避免覆盖更新。
- 测试输出 StarletteDeprecationWarning：当前实测版本仍可执行，属于测试客户端的未来弃用提示，已如实记录。

本项目定位为本地课程验收。默认只监听本机地址，不含公网部署、账号找回、验证码、自动保存未提交答案和题库等功能。浏览器刷新会丢失未提交答案；返回上一题会清除该题及其后路径的答案，以免旧分支数据混入。
