# 核心五表、Staff与ReservationAudit关系模式及规范化


**顾客入口与日期更新：** 已复用Guest联系人表加入无需账号的标准价直接预订，并将全部日期输入/日历改为英文；仍为7表/48列。说明见 [顾客预订与英文日期.md](../顾客预订与英文日期.md)。当前测试合计54项（17+14+18+5），另有Node日历自检。
版本2026-10-25，Jinxing Wu数据库工作包。后续增加Staff和ReservationAudit，当前RM由 `evidence/web_schema_columns.json` 的7表/48列实际元数据生成；旧 `schema_columns.json` 保留核心五表28列的历史快照。可编辑源为 `Hotel_Database_RM.drawio`，预览为 `Hotel_Database_RM.png`。

## 最终关系模式

核心五表及Staff主键使用INTEGER自动标识，ReservationAudit使用BIGINT自动标识。NN为NOT NULL；以下除明确NULL外均为NN。

```text
guest(guest_id PK, name, email NULL, phone)
room_type(room_type_id PK, type_name UQ, max_guests, base_nightly_rate)
room(room_id PK, room_number UQ, room_type_id FK, is_bookable, housekeeping_status)
reservation(reservation_id PK, guest_id FK, room_id FK,
  check_in_date, check_out_date, guest_count, booked_nightly_rate, created_at,
  status, actual_check_in_at NULL, actual_check_out_at NULL,
  previous_reservation_id FK NULL)
reservation_guest(reservation_guest_id PK, reservation_id FK, full_name)
staff(staff_id PK, username UQ, display_name, password_hash, role, is_active,
  must_change_password, session_version, failed_attempts,
  locked_until NULL, created_at)
reservation_audit(audit_id PK, reservation_id FK, staff_id FK NULL, source,
  action, occurred_at, reason, before_data NULL, after_data)
```

七条外键（原五条加审计两条）：room.room_type_id → room_type.room_type_id；reservation.guest_id → guest.guest_id；reservation.room_id → room.room_id；reservation.previous_reservation_id → reservation.reservation_id；reservation_guest.reservation_id → reservation.reservation_id。另有reservation_audit.reservation_id → reservation.reservation_id及reservation_audit.staff_id → staff.staff_id，全部ON DELETE RESTRICT，不级联抹去历史。

## 候选键与唯一性

| 关系 | 候选键 |
|---|---|
| guest | {guest_id} |
| room_type | {room_type_id}，{type_name} |
| room | {room_id}，{room_number} |
| reservation | {reservation_id} |
| reservation_guest | {reservation_guest_id} |
| staff | {staff_id}，{username} |
| reservation_audit | {audit_id} |

Staff由单独staff.sql迁移增加。staff_id和非空唯一username各自决定其余Staff属性；按这些已声明依赖满足BCNF。role为前台/经理两种取值，不假设role决定姓名、密码或账号状态。密码只存scrypt哈希，会话版本与错误次数是认证状态。

ReservationAudit通过两个外键关联订单及可空员工身份。audit_id决定事件其余属性；同一员工和同一订单均可对应多次事件，不能把staff_id或reservation_id作为事件键。before_data/after_data为历史快照JSONB，不是另一个实时业务资料来源。source在staff_id非空时固定为staff，是有意保存的条件冗余；JSONB内部也不作经典原子属性分解分析，因此不把此事件表与所有业务表一并无条件宣称严格BCNF。下文的核心模型及接续条件依赖分析仍适用。

姓名、电话、email都不假设唯一；email可NULL。名单允许同名。部分唯一索引只约束满足条件的行，不把previous_reservation_id或room_id变成reservation全表候选键。前段能有多个已取消接续尝试及至多1个未取消后段。

## ER映射

Guest、RoomType、Room、Reservation、ReservationGuest分别映射为五张表。四项普通1:N关系把外键放在N端，NN表达每笔订单、客房或入住登记对父实体的强制参与；父实体可暂时没有子记录。递归接续关系用可NULL的previous_reservation_id表达根段或单前驱。

名单在预订创建时允许为空；入住时人数等于guest_count是跨行时点约束，不把ER最小参与误画为1。Guest指预订联系人，ReservationGuest描述此段实际入住者，二者不合并为同一身份。

## 函数依赖

以下列出通常用于课程分析的全表函数依赖；可空前驱引出的条件依赖另列讨论，不能把以下列表当作完整接续语义的穷尽证明。

```text
guest_id → name, email, phone
room_type_id → type_name, max_guests, base_nightly_rate
type_name → room_type_id, max_guests, base_nightly_rate
room_id → room_number, room_type_id, is_bookable, housekeeping_status
room_number → room_id, room_type_id, is_bookable, housekeeping_status
reservation_id → guest_id, room_id, check_in_date, check_out_date,
  guest_count, booked_nightly_rate, created_at, status,
  actual_check_in_at, actual_check_out_at, previous_reservation_id
reservation_guest_id → reservation_id, full_name
```

这些依赖分别属于各自关系，不混成同一张宽表。特别是：room_id不决定所有历史订单的成交价；姓名不决定联系人或入住者身份；可空非唯一邮箱不决定guest_id；previous_reservation_id不是全关系唯一键。

## BCNF论证与无损性

就上述全表函数依赖而言，guest、room_type、room和reservation_guest的非平凡依赖均以超键为决定因素，可以论证到BCNF，因此也满足3NF。reservation不含接续前驱时，其核心属性也有同样的BCNF结构。列数不是判断依据，单独声明一个自增主键也不能代替检查其他业务依赖。

当前reservation加入可空previous_reservation_id后，需要补充接续条件依赖：在前驱非空的后段记录中，同一个previous_reservation_id决定同一guest_id和check_in_date，因为联系人必须相同，新段起日必须等于该前段离店日。前段又能有多个已取消的后段尝试，因此previous_reservation_id不是这个接续子关系的超键；guest_id和check_in_date也不是候选键属性。将该非空接续子关系按普通FD分析时，它不满足3NF或BCNF。

上述依赖仅针对非空前驱的记录：根订单的previous_reservation_id为NULL，联系人和起日可以不同，不能不加说明地将该依赖写成整个SQL表的无条件FD。经典FD/范式理论通常在不含NULL的关系上定义，因此完整SQL表的规范化说明应明确其空值处理和分析范围。不能只把之前的结论改成“全表肯定是3NF”来回避这一点。

更准确的结论是：四张基础表及reservation核心属性在列出的全表FD下达到BCNF；当前五表实现的接续部分保留条件冗余，须在设计取舍中说明，不能无条件声称所有业务子关系都严格BCNF。服务保持前驱、联系人和日期一致是运行完整性机制，不是消除了该依赖。

若后续选择让接续关系单独建模，可评估Continuation(next_reservation_id PK/FK, previous_reservation_id FK)，从reservation移出previous_reservation_id，再分别分析核心订单和接续关联。该二列表以next_reservation_id为键；它使关系分析清楚，但仍需跨表验证联系人和日期衔接，不能承诺消除全部业务冗余。此处只是备选设计，本次没有实施该接续拆分；第六、七张表分别用于员工身份和操作历史。

BCNF结论本身不保证日期冲突、容量或状态机正确，这些仍需相应业务约束及事务机制。

若从含房型资料的宽客房表出发，room_id → room_type_id → 房型名称、容量、基础价带来传递依赖。将其分解为Room与RoomType后，两表交集为room_type_id，它决定全部RoomType属性，所以该二元分解无损；客房和房型的依赖分别保留。当前最终模式已独立这两表，不虚构额外的分解步骤。

入住名单每人一行，而非occupant1、occupant2或逗号字符串。full_name在本应用视作单一显示值，未要求拆姓/名；同名记录不表示同一个人。该表没有自然人身份证件唯一假设。

## 设计取舍

- 成交每晚价是预订时快照，基础价是当前报价，语义不同。正常操作不回写历史成交价；示例1006保留110，即使Single当前基础价120。
- 不存total_amount、联系人姓名、房号、房型名或reservation.room_type_id；通过关联查询和日期差计算，减少更新异常。
- guest_count是计划人数，名单可晚于预订创建，因此两者并非全生命周期恒等；入住时匹配，由服务在订单锁下核验。
- 一段一房，延住关联新段，保留各段房间、日期和成交价。前驱固定且日期严格向后，可排除环；跨行条件仍由服务落实。
- 房间开放与清洁分开。dirty不等于所有未来日期不可订，checked_in才表示实际占用，未来confirmed表示计划占用。
- 房型容量和价格在演示期间不并发维护；不改已有订单房间/前驱，也不改变已有预订客房所属房型。开放这些维护功能前需扩充历史与锁策略。

与ER核对：5实体、28个物理属性、5条外键；概念ER中的关系映射为外键，无需重复画成属性。课堂notation最终由Zirui对讲义核验。

理论参考：Sibel Adali, CSCI4380 Lecture 5 Normalization（3NF与BCNF定义）；Antonio Badia and Daniel Lemire, Functional dependencies with null markers, Computer Journal 58(5), 2015, arXiv:1404.4963（NULL与经典FD的适用范围）。最终报告应按本课程讲义采用的分析口径表达。
