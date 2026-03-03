# PRD: IFC Graph + BIM Viewer 联动平台 (V1)

- 文档版本: v1.0
- 日期: 2026-03-03
- 状态: 已确认需求，待实施
- 范围: 单个 IFC 模型

## 1. 背景与目标

基于当前 `IFC2StructuredData` 的解析结果，构建一个工程可落地的 Property Graph 应用：

1. 左侧为 BIM 模型可视化（Viewer）。
2. 右侧为 Graph 可视化（局部子图为主，可回到全图）。
3. 左右联动双向跳转:
   - 点击左侧对象，高亮右侧对应节点。
   - 点击右侧节点，高亮左侧对应对象。

核心原则：

1. 图中的主节点是 `Building Object`（如 `IfcWall`, `IfcDoor` 等）。
2. 节点特征来自 `attribute.csv`。
3. 边来自 `relationships.csv`，保留 IFC 原始方向。
4. 几何采用“图核心 + 扩展资源”双层策略。

## 2. 已确认决策（需求冻结）

1. 图范式: Property Graph（Neo4j）。
2. 丢弃 `IfcMaterial/IfcClassification/IfcGroup` 相关节点和关系。
3. V1 仅支持单个 IFC。
4. 主键使用 `GlobalId`，不增加复合 ID。
5. 异构图两类节点:
   - `BuildingObject`
   - `GeometryDefinition`（geometry class）
6. FacetedBRep 对象仅存相对路径特征 `hasGeometryFilePath`，不额外存 bbox/顶点数等。
7. 渲染策略选择 A：预生成 GLB。
8. 单位统一为米（m）。
9. 需要双向联动 + 邻居展开 + geometry class 联动高亮。
10. 初期规模目标: <= 1000 节点（使用 `example_str` 测试）。
11. 右侧默认展示“以选中节点为中心的局部子图”，提供切换全图。
12. 关系方向保留原始 IFC 方向，不做反向冗余。
13. V1 不做论文中的 `RelSpatial/correspondsTo` 语义增强。
14. PRD 文档落地到仓库。

## 3. 范围定义

### 3.1 In Scope（V1）

1. 从现有输出加载:
   - `attribute.csv`
   - `relationships.csv`
   - `geometry_instance.csv`
   - `geometry_library.csv`
   - `geometry/*.obj/*.mtl`
   - `meta.json`
2. 构建 Neo4j 异构图（对象 + geometry class）。
3. 构建 Viewer 渲染资产（GLB + 索引）。
4. 前后端联动可视化。

### 3.2 Out of Scope（V1）

1. 多 IFC 联邦模型。
2. 跨学科语义增强（`correspondsTo` 等）。
3. 材料/分类/分组节点与关系。
4. 图中反向冗余边。

## 4. 数据输入与来源映射

1. `attribute.csv`: 对象节点属性来源。
2. `relationships.csv`: 对象间关系边来源。
3. `geometry_instance.csv`: 对象与几何的路由/实例信息。
4. `geometry_library.csv`: 参数化几何定义（去重后的 class）。
5. `geometry/*.obj`: FacetedBRep 几何文件路径来源。

## 5. 目标图模型（Neo4j）

## 5.1 节点类型

1. `:BuildingObject`
   - 主键: `GlobalId`（唯一约束）
   - 关键属性:
     - `ifcType`
     - `name`
     - `hasGeometry`
     - `geometryMethod`（来自 `geometry_instance.method`）
     - `attributesJson`（来自 `attribute.csv` 全量属性，JSON）
     - `hasGeometryFilePath`（仅 faceted_brep，相对路径）
2. `:GeometryDefinition`
   - 主键: `definitionId`
   - 属性:
     - `method`
     - `representationType`
     - `geometryTreeJson`
     - `instanceCount`

## 5.2 边类型

1. `(:BuildingObject)-[:RELATES_TO {relationshipType}]->(:BuildingObject)`
   - `relationshipType` 存 IFC 关系类型（如 `IfcRelAggregates`）
   - 方向严格遵守 CSV 中 `Relating -> Related`
2. `(:BuildingObject)-[:USES_GEOMETRY {instanceParamsJson}]->(:GeometryDefinition)`
   - 仅 `definition_id` 非空对象建立
   - `instanceParamsJson` 存放实例参数（如 `position` 或 `mapping_target`）

## 5.3 丢弃策略（显式缺陷）

以下关系将被过滤（不入图）：

1. 任一端点不是 `GlobalId` 对象节点（常见于 Material/Classification/Group）。
2. `IfcRelAssociatesMaterial`
3. `IfcRelAssociatesClassification`
4. `IfcRelAssignsToGroup`

影响说明：

1. 图中失去材料与分类语义。
2. 基于材料/分类的查询与分析不可用。
3. 该舍弃为 V1 工程取舍，后续版本可恢复为可选开关。

## 6. 几何存储与展示方案

## 6.1 图中的几何表达（语义层）

1. 参数化对象:
   - 通过 `USES_GEOMETRY` 指向 `GeometryDefinition`
   - 对象保留实例参数
2. FacetedBRep 对象:
   - 不创建 `GeometryDefinition`
   - 对象节点写入 `hasGeometryFilePath`（相对路径）

该设计与论文“core graph + extension layer + virtual link”一致：图里存可检索语义，重几何在扩展层文件系统。

## 6.2 Viewer 几何资产（渲染层）

为保证“混合几何全部可渲染”，V1 新增 `Viewer Asset Builder` 组件，输出:

1. `viewer/model.glb`: 全模型统一渲染资产。
2. `viewer/object_index.json`: `GlobalId -> glb nodeId/meshId` 映射。

实现策略：

1. 直接从 IFC 做一次完整 tessellation 生成渲染缓存（工程最稳）。
2. 与图语义解耦:
   - 图语义继续使用 CSV/OBJ 的混合抽象。
   - Viewer 只负责稳定高性能渲染与拾取。
3. 保持对象颗粒度:
   - GLB 中每个对象保留 `GlobalId` 元数据。

说明：

1. 不在前端实时重建 `geometry_tree` 为网格，避免浏览器端几何内核复杂度。
2. 该方案新增一个组件，但大幅降低渲染和一致性风险。

## 6.3 单位统一策略（米）

1. Viewer 输出全部为米。
2. 图中几何相关参数在入库时转换为米并记录 `unit = "m"`。
3. 原始属性值保留原值，同时增加可选 `normalized` 字段（仅对可识别长度字段）。

## 7. 系统架构

1. `Parser Output`（现有）:
   - 生成 CSV/OBJ/meta
2. `Graph Ingest Service`（新增）:
   - 读取 CSV
   - 过滤关系
   - 写入 Neo4j
3. `Viewer Asset Builder`（新增）:
   - IFC -> GLB + object index
4. `Backend API`（新增）:
   - 图查询
   - 对象详情
   - 邻域子图
   - 选中联动事件
5. `Frontend App`（新增）:
   - 左: 3D Viewer
   - 右: Graph View
   - 双向联动

建议技术栈：

1. Backend: Python + FastAPI + Neo4j Python Driver
2. Viewer: Three.js（或 react-three-fiber）
3. Graph UI: Cytoscape.js（局部子图交互稳定）
4. 状态同步: 前端全局状态（Zustand/Redux 二选一）

## 8. API 设计（V1）

1. `POST /api/import`
   - 输入: 输出目录路径
   - 行为: 导入 Neo4j + 生成 viewer 索引
2. `GET /api/object/{globalId}`
   - 返回对象属性、关联 geometry、可视化映射
3. `GET /api/graph/neighborhood?globalId=...&hops=1|2&limit=...`
   - 返回局部子图
4. `GET /api/graph/overview`
   - 返回全图摘要（节点/边统计）
5. `GET /api/viewer/index`
   - 返回 `GlobalId -> glb node` 映射

## 9. 前端交互需求

1. 左侧 Viewer：
   - 点击对象触发 `onSelect(GlobalId)`
   - 高亮选中对象
2. 右侧 Graph：
   - 默认展示选中节点 1-hop 邻域
   - 可切换 2-hop
   - 可切换“回到全图”
3. 双向联动：
   - Viewer 选中 -> Graph 定位并居中
   - Graph 选中 -> Viewer 定位并聚焦
4. Geometry class 交互：
   - 选中 `GeometryDefinition` 节点时，高亮所有实例对象

## 10. 性能目标（基于 <= 1000 节点）

1. 首次导入（图 + 资产索引）: < 60s（本地开发机）
2. 页面初次可交互: < 3s（缓存后）
3. 选中联动延迟: < 200ms
4. 1-hop 子图查询: < 100ms
5. 2-hop 子图查询: < 300ms

## 11. 验收标准（DoD）

1. 能成功导入 `example_str` 对应输出数据到 Neo4j。
2. `BuildingObject` 节点数量与 `attribute.csv` 中 `has_geometry=True` 对齐策略明确并可复核。
3. `RELATES_TO` 边数量等于过滤后关系数。
4. `USES_GEOMETRY` 边数量等于 `geometry_instance` 中 `definition_id` 非空行数。
5. FacetedBRep 对象节点均含 `hasGeometryFilePath` 且路径可解析。
6. 左右双向点击联动稳定可复现。
7. 可在局部子图与全图之间切换。

## 12. 风险与应对

1. 风险: 参数化几何在前端重建难度高。
   - 应对: V1 使用预生成 GLB 缓存。
2. 风险: 单位转换造成错位。
   - 应对: 入库与 viewer 统一米制，并增加对齐测试。
3. 风险: 丢弃 material/classification/group 降低语义完整性。
   - 应对: 在文档和 UI 显式标注 V1 限制。
4. 风险: 关系图过密影响可读性。
   - 应对: 默认局部子图 + 关系类型过滤器。

## 13. 实施顺序与完整排期（建议 6 周）

## Week 1: 数据与图模型打底

1. 固化 Neo4j schema（约束、索引、标签、关系类型）。
2. 实现 `Graph Ingest Service`（CSV 读取、过滤规则、批量写入）。
3. 完成关系过滤逻辑（明确丢弃项统计）。
4. 产出导入报告（节点数/边数/丢弃数）。

交付物：

1. `scripts/import_to_neo4j.py`
2. `docs/data_contract_graph.md`

## Week 2: 几何资产构建

1. 新建 `Viewer Asset Builder`。
2. IFC -> `model.glb` + `object_index.json`。
3. 验证对象颗粒度与 `GlobalId` 映射完整性。
4. 单位统一为米并做对齐测试。

交付物：

1. `scripts/build_viewer_assets.py`
2. `viewer/model.glb`
3. `viewer/object_index.json`

## Week 3: Backend API

1. FastAPI 项目骨架。
2. 完成对象详情、邻域子图、overview、viewer index 接口。
3. 加入查询性能基准与缓存策略（按需）。

交付物：

1. `backend/app.py`
2. `backend/services/graph_service.py`
3. OpenAPI 文档

## Week 4: 前端双面板原型

1. 左侧 Three.js viewer 加载 GLB。
2. 右侧 Cytoscape 局部子图渲染。
3. 完成双向联动（点击 -> 跳转/高亮）。

交付物：

1. `frontend` 初版可运行页面
2. 交互录屏（对象->图、图->对象）

## Week 5: 交互增强与稳定性

1. 1-hop/2-hop 切换。
2. “回到全图”模式。
3. GeometryDefinition 节点联动高亮实例对象。
4. 错误处理与空数据提示。

交付物：

1. 完整交互版前端
2. E2E 用例（关键路径）

## Week 6: 验收与文档

1. 用 `example_str` 跑全链路验收。
2. 性能与准确性对齐 DoD。
3. 输出操作手册、限制项清单、下阶段 backlog。

交付物：

1. `docs/runbook.md`
2. `docs/limitations_v1.md`
3. `docs/backlog_v2.md`

## 14. 下一阶段（V2）候选

1. 恢复 material/classification/group 为可选子图。
2. 多 IFC 联邦与跨模型关系。
3. 引入论文中的 `RelSpatial` 与 `correspondsTo` 语义增强流水线。
4. 增加变更传播与冲突检测能力。

