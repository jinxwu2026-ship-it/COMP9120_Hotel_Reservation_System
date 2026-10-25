# 数据库与 SQL 交接契约


**2026-10-25功能更新：** 已实现入住前修改、多房原子预订、经理固定优惠晚价和预订操作历史。升级/使用方法见根目录 [本次功能更新.md](../本次功能更新.md)。当前7表/48列；旧验证记录按其日期保留。
版本：2026-10-24。负责人：Jinxing Wu。依据最新五表设计及 Three Person Work Allocation；此文件明确 SQL 层合同，公开服务函数由 Tianyi 在 `service.py` 实现。

**接入版说明：** 本页对应保留的数据库独立验证接口。现有应用以 `../tianyishen/SQL_queries requirement.txt` 的28条位置参数和同目录queries.py为准，已接通并扩展service.py；改期、多房、优惠及审计SQL另在service.py内实现。尤其普通人工入住不再限制计划日期；此页原设计中的入住日期建议不用于覆盖当前服务。实测结果见该目录README和evidence。

## 调用约定

`queries.py` 仅包含25条SQL常量，无连接、输入、提交或回滚代码。由 Python 驱动执行：

```python
cursor.execute(queries.FIND_ROOMS, {
    "check_in": check_in, "check_out": check_out,
    "guests": guests, "room_type_id": room_type_id,
})
rows = cursor.fetchall()
```

此处演示 psycopg 风格的命名绑定，不能用 Python `%`、f-string 或字符串拼接替换用户输入。日期用 `date`；价格用 `Decimal`；实际时间用 aware `datetime`；整数数组用 `list[int]`；可空值用 `None`；BOOLEAN 用 `bool`。驱动选择、连接配置、事务上下文及异常到 `BookingError` 的转换由 Tianyi 负责。

下表输出按 SELECT / RETURNING 顺序列出。多行读取为空时为 `[]`；单行读取无记录为 `None`。条件修改无返回行表示前置条件不满足，服务必须拒绝或报告不存在，不能当作成功。数据库完整性错误会中止当前事务，调用方必须回滚后才能继续。只有 COMMIT 成功后才向菜单报告成功。

## SQL 常量与参数

| 常量 | 命名参数 | 输出列顺序 |
|---|---|---|
| GET_HOTEL_CLOCK | 无 | hotel_now, hotel_today |
| ADD_GUEST | name, email, phone | guest_id |
| LIST_TYPES | 无 | room_type_id, type_name, max_guests, base_nightly_rate |
| LIST_ROOMS | 无 | room_id, room_number, room_type_id, type_name, max_guests, base_nightly_rate, is_bookable, housekeeping_status |
| FIND_ROOMS | check_in, check_out, guests, room_type_id（可None） | room_id, room_number, room_type_id, type_name, max_guests, base_nightly_rate |
| LOCK_ROOMS | room_ids | room_id；去重后升序 |
| LOCK_RESERVATIONS | reservation_ids | reservation_id；去重后升序 |
| GET_ROOM | room_id | 同 LIST_ROOMS，最多1行 |
| GET_RESERVATION | reservation_id | reservation_id, guest_id, room_id, check_in_date, check_out_date, guest_count, booked_nightly_rate, created_at, status, actual_check_in_at, actual_check_out_at, previous_reservation_id |
| ROOM_DATE_CONFLICTS | room_id, check_in, check_out, exclude_reservation_id（可None） | reservation_id, check_in_date, check_out_date, status |
| CURRENT_OCCUPANTS | room_id, exclude_reservation_id（可None） | reservation_id |
| INSERT_RESERVATION | guest_id, room_id, check_in, check_out, guests, booked_nightly_rate, previous_reservation_id（普通单为None） | reservation_id, booked_nightly_rate, total_amount, status |
| PERSONAL_RESERVATIONS | guest_id | reservation_id, room_number, type_name, check_in_date, check_out_date, guest_count, booked_nightly_rate, total_amount, status, actual_check_in_at, actual_check_out_at, previous_reservation_id |
| CANCEL_RESERVATION | reservation_id, guest_id | reservation_id, status |
| ADD_STAYING_GUEST | reservation_id, full_name | reservation_guest_id |
| REMOVE_STAYING_GUEST | reservation_id, reservation_guest_id | reservation_guest_id |
| LIST_STAYING_GUESTS | reservation_id | reservation_guest_id, full_name |
| COPY_STAYING_GUESTS | previous_reservation_id, next_reservation_id | reservation_guest_id, full_name；新的登记ID，前段不删除 |
| MARK_CHECKED_IN | reservation_id, actual_at | reservation_id, status, actual_check_in_at |
| MARK_CHECKED_OUT | reservation_id, actual_at | reservation_id, status, actual_check_out_at |
| SET_ROOM_OPEN | room_id, is_open | room_id, is_bookable |
| SET_HOUSEKEEPING_STATUS | room_id, new_status | room_id, housekeeping_status；有人在住时无行 |
| GET_SUCCESSORS | reservation_id（前段ID） | reservation_id, room_id, check_in_date, check_out_date, status；排除cancelled，保留checked_out |
| EXTENSION_OPTIONS | reservation_id（当前在住段）, new_check_out | room_id, room_number, room_type_id, type_name, base_nightly_rate, check_in_date, check_out_date, guest_count, preference |
| BOOKING_STATISTICS | 无 | room_type_id, type_name, bookings, cancelled, booking_value |

`EXTENSION_OPTIONS.preference`：0原房，1其他同房型，2其他适合房型；同级按价格和房号排序。已有未取消后段、非在住前段、新离店日非法或需补写过去延住时无候选。它不预留库存，不检查未来那天能否完成清洁。

`FIND_ROOMS` 无结果也可能是非法日期或人数；菜单应先做明确的输入验证。`BOOKING_STATISTICS` 为全部订单数量、取消数、非取消计划金额，不是实收收入，不连接入住名单以免金额重复。

## 锁与事务的共同协议

隔离级别为 READ COMMITTED。所有会影响可售、入住或清洁的入口先取得涉及客房的锁，再取得相关订单锁：

1. 先读订单取得房间ID；已有订单的 room_id 在普通操作中不可改写。
2. `LOCK_ROOMS(room_ids)` 按房间ID升序；核对实际返回的ID完整匹配请求，缺房即拒绝。
3. `LOCK_RESERVATIONS(reservation_ids)` 按订单ID升序；核对缺失记录。
4. **锁完成后另发查询**读取房间、订单、冲突、实际入住者、名单、后继和当前价格。不得使用等锁前的旧结果。
5. 全部通过后执行修改；一次提交。错误、锁超时、死锁或无返回行按业务回滚。

名单维护仅需锁所属订单；不得在它之后反向请求房间锁。它与办理入住使用同一个订单锁，保证名单核验与冻结一致。多房换房一次请求两间房锁，不按“先旧后新”的顺序临时加锁。用户选择和报价确认均在写事务外完成。

## 各服务如何组合 SQL

| 公开服务 | SQL顺序与必须补充的业务检查 |
|---|---|
| create_reservation | 锁房 → GET_ROOM / ROOM_DATE_CONFLICTS / GET_HOTEL_CLOCK → 验证日期、容量、开放及联系人 → INSERT_RESERVATION，价格取锁后房型报价，前驱None |
| cancel_reservation | 锁房及订单 → GET_RESERVATION → CANCEL_RESERVATION；SQL本身同时检查归属、confirmed及今天早于入住日 |
| add/remove_staying_guest | 锁订单 → 核对confirmed → ADD/REMOVE；登记姓名非空白，同名允许；预订人若入住也须登记 |
| check_in | 锁房及订单 → GET_RESERVATION / GET_ROOM / CURRENT_OCCUPANTS / LIST_STAYING_GUESTS → 仅普通confirmed、今天在计划区间、开放且clean、无其他实际入住、名单数等于guest_count → MARK_CHECKED_IN |
| check_out | 锁房及订单 → 确认checked_in → MARK_CHECKED_OUT + SET_HOUSEKEEPING_STATUS(dirty) → 同一次提交；不得自动关闭预订开关 |
| set_room_open | 锁房 → SET_ROOM_OPEN；已有订单不取消 |
| set_housekeeping_status | 锁房 → CURRENT_OCCUPANTS → 检查允许的清洁转换 → SET_HOUSEKEEPING_STATUS；clean不自动开放停用房 |
| create_extension | 先收集同意 → 锁原房和目标房、锁前段 → 重查checked_in、无未取消后继、日期衔接、同联系人、目标开放、容量、日期冲突及当前价格 → accepted_rate与当前价不同即回滚重报 → INSERT_RESERVATION（带前驱）及可选COPY_STAYING_GUESTS |
| activate_continuation | 锁两房及两段 → 验证前段checked_in、后段confirmed、联系人相同、日期相接、今天位于新段区间、名单完整、目标开放且clean → 当前入住检查仅在原房接续时排除前段 → 以同一actual_at结束旧段并启动新段；换房额外将旧房dirty，同房不置dirty → 一次提交 |

新段创建不会结束旧段；取消/无房/不同意不改旧单。接续激活不能直接调用普通退房再另开入住事务。普通 `check_in` 不得绕过接续激活流程办理有前驱的订单。普通提前退房若存在未取消后段，建议先拒绝并引导处理后段，具体人工政策由小组定稿。

接续日期必须等于前段计划离店日且至少一晚，前驱固定不改；沿链日期严格递增因而无环。锁父段并检查 `GET_SUCCESSORS`；部分唯一索引再保护“最多一个未取消后继”。没有额外的全局 UNIQUE(previous_reservation_id)，已取消尝试可保留。

## 已保护与尚需服务保护

DDL保护五表PK、FK、必填、非空白、唯一房号/房型名、正人数/容量、非负且非NaN价格、有限日期/时间、日期顺序、实际时间组合、禁止自指、单房最多一笔checked_in、每前段最多一笔未取消后继。唯一索引仅限制当前物理入住数量和接续数量。

**日期重叠不是数据库硬约束。** `ix_reservation_active_dates` 只是查询索引；SQL只有在全部入口遵守锁协议时才能防止并发重复预订。直接INSERT能够写入重叠、超容量、未清洁入住、名单不符、非法状态转换或错误跨行接续。约束测试明确验证并记录此边界，不能在报告中声称任意手工SQL也被防住。需要所有数据库写入口都强制此规则时再共同评估触发器/数据库函数/排斥约束，当前版本不引入另一套业务实现。

房型容量、价格和已预订客房的所属房型在演示中冻结维护；若开放并发修改，必须扩展锁协议。历史订单的房间、人数、计划日期、成交价和前驱不由普通菜单原地修改。没有历史删除菜单；RESTRICT只禁止被引用数据删除，不能防止所有任意手工删除。

当前基线：email可空且不唯一，电话必填但不唯一，价格>=0。币种仍需小组统一，数据库不存币种列。邮箱、零价和报价策略变更须同步字典、DDL、SQL、服务、样例及测试。

## 测试证据边界

`verify_database.py` 使用真实 PostgreSQL：将25个模板转为服务端 PREPARE/EXECUTE，并对35个固定输入场景断言结果；另做约束、数据库锁协议和故障回滚检查。该工具中的字面量替换仅用于固定测试夹具，不能复制到用户输入路径。该工具自身不测试Python服务；新增应用集成测试已验证真实psycopg2绑定、公开服务、原房/换房事务和服务并发，并补做菜单烟雾检查。详见 `../tianyishen/evidence/INTEGRATION_RESULTS.md`。
