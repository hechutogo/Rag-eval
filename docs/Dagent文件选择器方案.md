# Dagent 文件可视化选择器方案

## 一、需求背景

当前从 Dagent 导入时，用户需要手动输入逗号分隔的文件 ID，无法直观看到文件内容和进行选择。需要增加可视化文件选择器功能，让用户可以：
1. 查看文件列表（文件名、类型、大小、状态）
2. 直观选择需要的文件
3. 支持全选、搜索、分页

## 二、当前状态分析

### 现有 API
- `GET /api/qa-gen/dagent/files?org_id=xxx` - 返回 207 个文件的列表
  - 字段：`id, file_name, file_type, file_clean_status, file_bytes, create_time`

### 现有前端 UI
- 简单的 `Input.TextArea` 用于输入文件 ID
- 没有可视化选择界面

## 三、技术方案

### 1. 后端 API（无变化）
现有 API 已足够，无需新增接口。文件列表数据包含：
- `id`：文件唯一标识（用于选择）
- `file_name`：文件名（用于展示）
- `file_type`：文件类型（HTML/PDF/DOCX）
- `file_clean_status`：处理状态（用于状态提示）
- `file_bytes`：文件大小（格式化展示）
- `create_time`：创建时间

### 2. 前端组件设计

#### 2.1 文件选择器组件
创建一个独立的文件选择器组件，支持以下功能：

**UI 元素：**
- 文件列表表格（支持多选）
- 搜索框（按文件名搜索）
- 状态筛选器（按 file_clean_status 筛选）
- 全选/反选按钮
- 分页组件（每页显示 20 个文件）
- 已选择文件计数

**表格列：**
1. 选择列（复选框）
2. 文件名（可点击查看详情）
3. 文件类型
4. 文件大小（格式化为 KB/MB）
5. 处理状态（标签显示）
6. 创建时间

#### 2.2 文件详情弹窗
点击文件名时显示：
- 文件基本信息
- 段落统计（如果后端支持）
- 预览按钮（如果需要）

#### 2.3 与现有表单的集成
- 使用 `Form.Item` 包裹选择器组件
- 选中的文件 ID 存储在隐藏的 `file_ids` 字段中
- 保持向后兼容（支持手动输入）

### 3. 实现步骤

#### 步骤 1：创建文件选择器组件
```typescript
// src/components/DagentFileSelector/index.tsx
import { useState, useEffect } from 'react'
import { Table, Input, Button, Tag, Space, Modal, message, Pagination } from 'antd'
import { qaGenApi } from '../../services/api'

interface FileItem {
  id: string
  file_name: string
  file_type: string
  file_clean_status: string
  file_bytes: number
  create_time: string
}

interface DagentFileSelectorProps {
  orgId: string
  value?: string[] // 选中的文件ID数组
  onChange?: (fileIds: string[]) => void
}
```

#### 步骤 2：更新 QaGen 页面
- 将现有的 `Input.TextArea` 替换为 `DagentFileSelector`
- 保留原有的 `file_ids` 字段作为隐藏字段
- 添加文件选择器触发按钮

#### 步骤 3：添加交互逻辑
- 点击"选择文件"按钮打开选择器弹窗
- 选择完成后关闭弹窗，更新隐藏字段
- 显示已选择的文件数量和文件名摘要

### 4. 状态设计

```typescript
const [files, setFiles] = useState<FileItem[]>([])
const [loading, setLoading] = useState(false)
const [searchText, setSearchText] = useState('')
const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([])
const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 })
```

### 5. 文件格式化和状态显示

**文件大小格式化：**
```typescript
const formatFileSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
```

**状态标签：**
```typescript
const statusTag = (status: string) => {
  const map = {
    'CLEAN_FINISH': { color: 'success', label: '已处理' },
    'CLEAN_PROCESSING': { color: 'processing', label: '处理中' },
    'CLEAN_FAILED': { color: 'error', label: '处理失败' },
    'UPLOAD_FAILED': { color: 'warning', label: '上传失败' }
  }
  const cfg = map[status] || { color: 'default', label: status }
  return <Tag color={cfg.color}>{cfg.label}</Tag>
}
```

### 6. 性能优化

1. **分页加载**：每次只加载当前页的文件
2. **虚拟滚动**：如果文件数量很多（>1000），考虑虚拟滚动
3. **数据缓存**：文件列表数据缓存 5 分钟
4. **防抖搜索**：搜索输入使用防抖，避免频繁请求

### 7. 用户体验设计

#### 7.1 选择流程
1. 用户输入 org_id 并查询统计信息
2. 显示"选择文件"按钮（仅在获取到统计信息后启用）
3. 点击按钮打开文件选择器
4. 选择文件并确认
5. 返回表单，显示已选择文件摘要

#### 7.2 确认对话框
用户确认选择时显示：
- 已选择文件数量
- 预计生成的问题数（文件数 × 段落平均数 × 每段落问题数）
- 确认按钮

### 8. 扩展功能考虑

#### 8.1 段落预览
如果后端支持，可以添加：
- `GET /api/qa-gen/dagent/file/{file_id}/paragraphs` - 获取文件段落列表
- 点击文件时显示段落预览

#### 8.2 智能筛选
- 按文件类型筛选（HTML/PDF/DOCX）
- 按处理状态筛选
- 按文件大小筛选

#### 8.3 批量操作
- 按文件夹/目录批量选择
- 按文件名模式匹配选择

## 四、实施计划

### 第一阶段：基础文件选择器（1-2天）
1. 创建 `DagentFileSelector` 组件
2. 集成到 QaGen 页面
3. 实现基本的多选功能

### 第二阶段：增强功能（1-2天）
1. 添加搜索和筛选功能
2. 添加分页支持
3. 优化性能和用户体验

### 第三阶段：高级功能（可选）
1. 文件详情预览
2. 段落统计显示
3. 批量选择模式

## 五、API 接口说明

### 现有接口
```http
GET /api/qa-gen/dagent/files?org_id=xxx
```

### 响应格式
```json
{
  "status": 0,
  "data": [
    {
      "id": "file_123",
      "file_name": "linux_development.md",
      "file_type": "html",
      "file_clean_status": "CLEAN_FINISH",
      "file_bytes": 20480,
      "create_time": "2024-01-01 10:00:00"
    }
  ]
}
```

## 六、前端组件结构

```
QaGen/index.tsx
├── Form.Item name="file_ids"
│   └── <DagentFileSelector>
│       ├── <Button>选择文件</Button>
│       ├── <Modal>文件选择器
│       │   ├── <Input.Search>搜索框
│       │   ├── <Table>文件列表
│       │   │   ├── 选择列
│       │   │   ├── 文件名
│       │   │   ├── 文件类型
│       │   │   ├── 文件大小
│       │   │   ├── 处理状态
│       │   │   └── 创建时间
│       │   ├── <Pagination>分页
│       │   └── <Space>操作按钮
│       └── 已选择文件摘要
```

## 七、注意事项

1. **向后兼容**：保持支持手动输入文件 ID
2. **错误处理**：网络错误、空状态处理
3. **移动端适配**：表格在小屏幕下的显示优化
4. **无障碍访问**：支持键盘导航和屏幕阅读器
5. **国际化**：标签和提示语的国际化支持

## 八、测试计划

1. **功能测试**：
   - 文件列表加载
   - 多选功能
   - 搜索筛选
   - 分页切换
   - 表单数据同步

2. **性能测试**：
   - 207 个文件的加载时间
   - 搜索响应时间
   - 内存占用

3. **兼容性测试**：
   - 不同浏览器
   - 不同屏幕尺寸
   - 键盘操作

## 九、风险评估

1. **API 性能**：207 个文件一次性加载可能较慢 → 实施分页
2. **内存占用**：大量 DOM 元素可能影响性能 → 虚拟滚动
3. **用户体验**：选择过程复杂 → 简化操作流程
4. **向后兼容**：确保现有手动输入功能正常工作

## 十、成功指标

1. **功能完整性**：100% 覆盖需求功能
2. **性能指标**：文件列表加载时间 < 2 秒
3. **用户体验**：选择流程步骤 ≤ 3 步
4. **代码质量**：无 TypeScript 错误，测试覆盖率 > 80%