# Jinxing 数据库交付与使用说明


**顾客入口与日期更新：** 已复用Guest联系人表加入无需账号的标准价直接预订，并将全部日期输入/日历改为英文；仍为7表/48列。说明见 [顾客预订与英文日期.md](../顾客预订与英文日期.md)。当前测试合计54项（17+14+18+5），另有Node日历自检。

**2026-10-25功能更新：** 已实现入住前修改、多房原子预订、经理固定优惠晚价和预订操作历史。升级/使用方法见根目录 [本次功能更新.md](../本次功能更新.md)。当前7表/48列；旧验证记录按其日期保留。
**网页/Staff更新：** 已新增staff.sql迁移、个人员工登录和低权限hotel_app，总计7表/48列，并已加入reservation_audit.sql。接收测试包者优先看根目录方案修改.md的pgAdmin流程，以及网页与员工账号运行.md；本文五表及旧验证内容指核心酒店模型。

本交付依据 `COMP9120_Three_Person_Work_Allocation(1).docx`，覆盖建库、约束、核心SQL、RM/规范化、数据库验证及数据库报告素材，原分工仍供报告核对；后续按用户授权扩展了Python服务、CLI及网页，不据此重新分配成员贡献。

**2026-10-24接入更新：** 队友Python服务已接通，运行入口为 `python tianyishen/main.py`，集成说明见 `../tianyishen/README.md`。应用使用该目录的28条位置参数SQL；本目录queries.py保留原25条命名参数SQL用于独立数据库验证，两个接口不能直接替换。

## 已建立的本机数据库

| 项目 | 值 |
|---|---|
| PostgreSQL | 16.14 |
| 主机与端口 | 127.0.0.1:55432 |
| 演示库 | comp9120_hotel |
| 隔离测试库 | comp9120_hotel_test |
| 本机管理角色 | hotel_owner |
| 酒店时区 | Australia/Sydney |
| 数据目录 | 作业目录下 .local/postgres |
| 本机密码文件 | 作业目录下 .local/pgpass.conf，已由.gitignore排除 |

这是新建的独立集群，原5432服务未修改。只监听本机回环地址并使用SCRAM密码认证。hotel_owner是此独立演示集群的管理角色；网页现使用独立低权限hotel_app，Staff认证另由应用管理；hotel_owner保留环境维护职责。

以下命令从作业目录运行。密码已经生成并保存在本机文件，不写入示例、报告或共享附件：

```powershell
$env:PGHOST = '127.0.0.1'
$env:PGPORT = '55432'
$env:PGUSER = 'hotel_owner'
$env:PGDATABASE = 'comp9120_hotel'
$env:PGPASSFILE = (Resolve-Path '.local\pgpass.conf').Path
& 'C:\Program Files\PostgreSQL\16\bin\psql.exe' -X -w
```

pgAdmin连接填写同样主机、端口、数据库和用户名，密码从自己的本机密码文件取得。不要把该文件传给队友；队友运行自己的数据库。

电脑重启后如果独立实例未运行：

```powershell
& 'C:\Program Files\PostgreSQL\16\bin\pg_ctl.exe' -D '.local\postgres' -l '.local\postgres-server.log' -w start
```

结束使用时正常停止：

```powershell
& 'C:\Program Files\PostgreSQL\16\bin\pg_ctl.exe' -D '.local\postgres' -m fast -w stop
```

不使用强制结束进程，不删除数据目录。没有设置自动启动任务或修改Windows服务。

## 文件与交付

| 文件 | 用途 |
|---|---|
| create_database.sql | 从postgres库创建演示库和测试库，设置数据库时区 |
| schema.sql | 五张核心业务表、键、基本完整性、两项条件唯一性和查询索引 |
| reservation_audit.sql | 预订事件表迁移，关联订单及可空员工身份 |
| staff.sql | 额外员工身份迁移；网页/CLI认证使用，密码不放SQL种子 |
| seed.sql | 4名联系人、3房型、6房间、14订单、11入住登记 |
| seed_more.sql | 一次性追加虚构演示数据，扩充后为50联系人、8房型、40房间、200订单、351入住登记 |
| generate_demo_expansion.py / verify_expanded_data.py | 生成扩充SQL / 在随机测试schema验证扩充数据及服务调用 |
| queries.py | 25条命名参数SQL供数据库独立验证；接入版使用tianyishen/queries.py的28条位置参数SQL |
| SQL_CONTRACT.md | 每条参数和返回列、锁顺序、服务前置条件及边界 |
| sql_examples.sql | 35个可直接运行的参数示例，每段ROLLBACK |
| test_constraints.sql | 43项约束/正常检查及1项明确边界，最后ROLLBACK |
| verify_database.py | 实际验证模板、结果、双连接和故障回滚；标准库+psql |
| Hotel_Database_RM.drawio / .png | 可编辑关系模式与预览 |
| RM_AND_NORMALISATION.md | 候选键、外键、函数依赖、BCNF及取舍 |
| REPORT_DATABASE.md | 可合并的报告第3章和第4章SQL/完整性素材 |
| evidence/ | 真实运行结果、结构快照及交付版本校验值 |

schema与seed均使用事务，遇到错误立即停止。脚本不包含DROP、TRUNCATE或自动清库；重复导入已有表/样例会报错并回滚，不能作为升级脚本使用。

七个.sql文件均采用W6课堂风格：使用块注释、对齐缩进、规范空格；建表约束集中放在表末，简单样例记录每行一个INSERT。不包含psql专用的 `\set` 行。schema和seed用于空schema；seed_more在基础seed之后追加一次；test_constraints和sql_examples仅在隔离测试库运行。create_database中的每条CREATE DATABASE需在postgres连接、开启autocommit后单独执行，不能包在BEGIN里。现有演示库无需重跑初始化或扩充。

## 课程要求和组内交付的区别

核对依据是Project Brief第4.3、4.4节及第7节，以及Project Rubric第3、4评分项。课程要求关系模式、键、函数依赖、规范化理由、可运行PostgreSQL和足够数据、代表SQL、完整性机制，以及真实多步骤事务的失败、回滚和并发解释。没有规定表数、SQL条数或测试用例数量，也没有要求使用某个自动化测试框架。

课程没有指定test_constraints.sql或sql_examples.sql两个文件名；它们分别用于复现约束验证和代表SQL。真实手动执行记录也可以形成证据。你提供的三人分工表将两者列入Jinxing的工作包，因此保留为组内约定交付物，不把它们称作教师强制文件。

schema、seed、应用SQL和RM/规范化说明是你这部分的主要技术材料；create_database是环境准备脚本，test_constraints、sql_examples、verify_database是辅助复现与开发验证材料。测试助手中的PL/pgSQL函数不是Brief或Rubric指定必须编写的功能，不需要把助手实现作为项目业务创新点。

当前实现已覆盖你的主要技术职责，但正式提交仍需整理三项证据：在报告第3章正文列出关键FD和BCNF理由并放入RM；在第4章正文选择少量实际SQL、结果和约束拒绝案例；与事务负责人共同解释锁和回滚。不要只引用附件或把所有日志放到正文。

必须说明日期防重叠、容量和名单属于受控服务事务的保护范围，不能把普通索引或基本CHECK说成可拒绝所有手工违规SQL。最终ER与RM的一致性、以及使用技术是否在Week10讲义范围内仍需小组对照讲义复核。只看Brief/Rubric与现有文件，不能承诺具体分数。

## 队友从空库复现

机器需已有PostgreSQL，提供有建库权限的本机账号。设置自己的PGHOST/PGPORT/PGUSER及认证后：

```powershell
psql -X -v ON_ERROR_STOP=1 -d postgres -f database/create_database.sql
psql -X -v ON_ERROR_STOP=1 -d comp9120_hotel -f database/schema.sql
psql -X -v ON_ERROR_STOP=1 -d comp9120_hotel -f database/seed.sql
psql -X -v ON_ERROR_STOP=1 -d comp9120_hotel -f database/seed_more.sql
psql -X -v ON_ERROR_STOP=1 -d comp9120_hotel_test -f database/schema.sql
psql -X -v ON_ERROR_STOP=1 -d comp9120_hotel_test -f database/seed.sql
```

create_database.sql只用于这两个名字尚不存在的环境；已有数据不要删除重跑。安装到另一空数据库时可跳过建库文件，先给目标库设置Sydney时区。schema和seed没有硬编码数据库名。

演示库导入seed_more后为200订单；独立数据库验证器使用的测试库仅导入最小seed，保留其固定预期结果。扩充检查可另运行 `python database/verify_expanded_data.py`，复用集成服务的psycopg2与随机测试schema，不修改演示库。

本机已完成初始化，不需要再次导入。验证脚本需要测试库仍是当天seed生成的原样夹具；日期跨日后要在**另建的空测试库**重新初始化，不以清空演示库刷新数据。测试库名需以 `_test` 结尾，验证器会拒绝其他库名。

## 执行检查

```powershell
psql -X -w -v ON_ERROR_STOP=1 -d comp9120_hotel_test -f database/test_constraints.sql
psql -X -w -v ON_ERROR_STOP=1 -d comp9120_hotel_test -f database/sql_examples.sql
python database/verify_database.py --host 127.0.0.1 --port 55432 --user hotel_owner --database comp9120_hotel_test
```

`verify_database.py`只需要Python 3标准库与psql。若psql不在PATH，验证器可传 `--psql` 绝对路径。`--write-examples` 根据当前queries.py刷新独立示例。结构或SQL变化后必须重新生成示例并复测。新增的`verify_expanded_data.py`复用`../tianyishen`测试助手与psycopg2，需要完整集成目录；数据库单独包仍可直接执行扩充SQL，生成器只用Python标准库。

所有约束和模板检查均回滚；并发检查只在隔离测试库临时提交两个专用负ID的竞争记录，检查后删除这两条。不会清理演示库，也不会清理其他ID的用户数据。回滚不会回收序列号，因此测试后ID出现空缺正常。

## 样例快速理解

seed以初始化当日Sydney日期D为基准：201房的1001在住，1002是去301的未来接续；1012为同一前段的取消尝试。1013与1014演示101房当天原房接续。1003与1004的日期相邻；102和202待清洁但保留未来预订；302停用且cleaning。四种订单状态、三种清洁状态均已覆盖。

最小seed夹具的实测统计为Single 6单/取消0/非取消金额1300；Double 4单/取消1/1080；Family 4单/取消2/940，总额3320。总额是计划预订金额，不是已收收入；这不是扩充后演示库的当前统计。

2026-10-24已向本机演示库追加样例：当前五表依次为50、8、40、200、351行，逐行确认原有记录全部保留。包含更多历史、未来和当前订单，以及11对历史接续；日期按导入当天计算，不会每天自动刷新。扩充导入、检查及真实查询计划见 `evidence/data_expansion*`。**本机勿重复导入seed_more.sql。** 网页、员工认证、低权限数据库角色及接续拆表的评估见根目录 `../备忘录.md`，网页和Staff已按后续授权实现，接续拆表仍未实施。

## 当前完成度与下一步

已完成：从空库建表和填充、43项约束/正常检查、25个SQL模板的35个场景、一次真实双连接锁竞争、一次故障回滚。详见证据文件。

应用接入已通过17项真实服务集成测试，覆盖实际驱动绑定、入住退房、原房/换房接续、失败回滚及服务层两连接竞争；记录见 `../tianyishen/evidence/INTEGRATION_RESULTS.md`。Zirui可继续独立业务验收并按课程要求整理最终证据。**数据库目前不会独自拒绝所有日期重叠或超容量写入**；服务路径已验证统一锁协议，任意手工SQL仍可绕过。

AI辅助参与SQL、测试和说明整理；成员须理解、复核，并在提交时按课程要求声明。分工分值不是实际贡献比例，贡献说明应依据真正完成的产出填写。
