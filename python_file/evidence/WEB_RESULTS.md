# 网页与员工认证验证结果

英文界面更新：2026-10-24。全部模板、网页/认证提示与错误使用英文，HTML语言为en。14项现有网页测试再次通过，见english_web_validation.txt。web_dashboard.png与web_staff.png已更新为英文版隔离预览。仅两个初始账号未自定义的默认显示名称改为英文；未修改密码、权限或业务流程。

2026-10-24，真实PostgreSQL 16.14、Python 3.12、Flask 3.1.3、Waitress 3.0.2。

- 14项网页/认证测试通过，见web_validation.txt。
- 原17项服务事务回归通过，见web_service_regression.txt。
- 从ZIP解压副本重跑14项网页、17项服务和扩充数据验证，全部通过，见package_reproduction.txt。
- live hotel_app权限与初始密码登录/强制改密页通过，见../../database/evidence/web_setup.json；未修改真实初始密码。
- 本机业务表保持50/8/40/200/351行，另有2个Staff。六表39列、14个索引（含主键/唯一索引），原5个FK不变。
- 浏览器在隔离复制数据上确认员工登录、工作台、员工管理、精确查单、订单详情与原房/换房接续入口。web_dashboard.png、web_staff.png是该隔离账号的预览；未通过浏览器修改真实业务数据或员工密码。
- 所有随机测试schema和8081测试服务均已清理，最终8080服务使用独立hotel_app。

测试中的SQLSTATE 22012为主动注入的回滚故障，不是未解决失败。
未做：异机安装、公网/HTTPS、真实手机、顾客账户、完整员工操作审计、接续拆表。原Customer CLI仍是持有本地DB凭据的开发入口，Guest ID不代表顾客身份认证。
