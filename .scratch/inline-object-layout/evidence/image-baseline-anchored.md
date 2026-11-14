## 2.2 表图题注验证 {#表图题注验证 snippet-docx-section="[2, 2]"}

本段验证 2.2 中的原生题注与旧题注兼容。

`anchor:begin:table`

  月份   发电量
  ------ --------
  一月   101
  二月   202

  : 表 9.9-7 月度统计

`anchor:end:table`

`anchor:begin:figure`

![图 9.9-7 场区布置](layout.png){width="10cm"}

`anchor:end:figure`

`anchor:begin:table`

  方案   指标
  ------ ------
  A      12

  : 新表题

表 8.8-9 兼容旧表题

`anchor:end:table`

`anchor:begin:figure`

图 8.8-9 兼容旧图题

![新图题](layout.png){width="10cm"}

`anchor:end:figure`

`anchor:begin:table`

  无题表   数值
  -------- ------
  A        1

`anchor:end:table`

`anchor:begin:table`

  独立对象   数值
  ---------- ------
  A          1

  : 重复标题

`anchor:end:table`

`anchor:begin:table`

  独立对象   数值
  ---------- ------
  B          2

  : 重复标题

`anchor:end:table`

### 2.2.3 分节计数 {#分节计数 snippet-docx-section="[2, 2, 3]"}

`anchor:begin:table`

  分节   数值
  ------ ------
  A      3

  : 分节统计

`anchor:end:table`

#### 2.2.3.1 深层计数共享 {#深层计数共享 snippet-docx-section="[2, 2, 3, 1]"}

`anchor:begin:table`

  层级   数值
  ------ ------
  深层   4

  : 深层统计

`anchor:end:table`

`anchor:begin:landscape`

`anchor:begin:table`

  方案   甲   乙   丙
  ------ ---- ---- ----
  横向   1    2    3

  : 横向表

`anchor:end:table`

`anchor:begin:figure`

[![横向图](layout.png){width="10cm"}](https://example.com)

`anchor:end:figure`

`anchor:end:landscape`
