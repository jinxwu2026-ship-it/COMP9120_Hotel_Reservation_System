# 数据库实测证据

**网页/Staff后续更新：** `web_setup.json`记录真实hotel_app权限、初始Staff及业务表数量；`web_schema_columns.json`为当前6表/39列元数据。原schema_columns.json及数据库阶段日志保留历史范围；当前RM已经包含Staff。网页14项和服务17项回归另见 `../../tianyishen/evidence/web_validation.txt` 与 `web_service_regression.txt`。

执行日期：2026-10-24，时区Australia/Sydney。PostgreSQL 16.14，真实本机独立集群，非模拟数据库。

本目录保留初次数据库阶段的记录。后续应用集成的实际通过结果另见 `../../tianyishen/evidence/INTEGRATION_RESULTS.md`；下文未执行范围仅针对初次数据库阶段，不再代表整个项目当前完成度。

后续样例扩充已完成：当前演示库五表为50、8、40、200、351行，原记录逐行确认保留。最新数量及查询计划见 `data_expansion.json`，实际psql导入输出见 `data_expansion_import.txt`，隔离扩充验证见 `data_expansion_validation.txt`；17项服务回归输出另见 `../../tianyishen/evidence/data_expansion_regression.txt`。下文14单数量与旧SQL预期仅指最小夹具及扩充前快照。

| 文件 | 证据范围 |
|---|---|
| database_snapshot.txt | 演示库、时区、五表记录数量、CHECK/FK/PK/UQ及索引定义 |
| schema_columns.json | 实际28列的名称、类型、空值、identity及默认值，RM生成依据 |
| database_validation.txt | 43项约束/正常检查、1项明确边界、35个SQL场景、两连接锁竞争及故障回滚 |
| sql_examples_output.txt | 由queries.py生成的独立PREPARE/EXECUTE示例的实际运行输出 |
| source_sha256.json | 与本次交付对应的源码、说明和RM文件SHA256校验值 |
| schema_format_validation.txt | W6格式调整后与原库28列、29项约束及12个索引等价；新schema的43项检查通过，原数据数量未变 |
| all_sql_format_validation.txt | 五份SQL格式统一后的空schema建库与样例、43项约束、35项SQL、独立示例及并发回滚复测；现有数据未变 |

格式调整后的17项服务回归也全部通过，原始输出另见 `../../tianyishen/evidence/schema_format_regression.txt`。

约束失败测试核验真实SQLSTATE，不把“SQL报错”笼统当作通过。SQL模板测试同时核验服务端参数推断、真实执行及预期结果，覆盖全部25个常量。

两连接测试中A先持有客房锁并暂停，B等待同一锁；锁后各自重新查冲突，最终仅1笔成功。故障注入在写退房状态后、写房态前制造数据库错误，新连接确认两处都保留原状态。

未执行：实际Python驱动适配、Tianyi的service公开函数、菜单、完整原房/换房接续事务、Zirui的集成验收及服务层并发。这些不包含在上述通过数量中。直接任意SQL可越过容量、重叠、状态机等服务规则，已在约束测试中明确记录。

序列号在回滚后可能增长，不能以ID不连续判定测试破坏数据。初次验证结束时演示库为4联系人、3房型、6房间、14订单、11入住登记；后续扩充数量见本页开头。测试只操作隔离测试库。
