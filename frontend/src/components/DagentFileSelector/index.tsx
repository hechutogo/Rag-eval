import React, { useState, useEffect } from 'react'
import { Table, Input, Button, Tag, Space, message, Pagination, Typography } from 'antd'
import { SearchOutlined, ReloadOutlined, CheckCircleOutlined } from '@ant-design/icons'
import { qaGenApi } from '../../services/api'

const { Text } = Typography

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
  envUrl?: string  // Dagent 环境 URL
  value?: string | string[] // 选中的文件ID（逗号分隔字符串或数组）
  onChange?: (fileIds: string | string[]) => void
  disabled?: boolean
}

const DagentFileSelector: React.FC<DagentFileSelectorProps> = ({
  orgId,
  envUrl = '',
  value = [],
  onChange,
  disabled = false,
}) => {
  const [files, setFiles] = useState<FileItem[]>([])
  const [loading, setLoading] = useState(false)
  const [searchText, setSearchText] = useState('')
  // 转换value为数组格式
  const valueToArray = (val: string | string[] | undefined): string[] => {
    if (!val) return []
    if (Array.isArray(val)) return val
    return val.split(',').map(id => id.trim()).filter(id => id.length > 0)
  }

  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>(valueToArray(value))
  const [pagination, setPagination] = useState({
    current: 1,
    pageSize: 20,
    total: 0,
  })

  // 加载文件列表
  const loadFiles = async (page = 1, pageSize = 20) => {
    if (!orgId || orgId.length < 8) return

    setLoading(true)
    try {
      const res = await qaGenApi.listDagentFiles(orgId, envUrl) as any
      const fileList = res.data || []
      setFiles(fileList)
      setPagination(prev => ({
        ...prev,
        total: fileList.length,
        current: page,
        pageSize,
      }))
    } catch (e: any) {
      console.error('加载文件列表失败:', e)
      message.error(`加载文件列表失败: ${e.message || '未知错误'}`)
      setFiles([])
    } finally {
      setLoading(false)
    }
  }

  // 初始化加载
  useEffect(() => {
    if (orgId && orgId.length >= 8) {
      loadFiles()
    } else {
      setFiles([])
      setSelectedRowKeys([])
    }
  }, [orgId, envUrl])

  // 同步选中状态到外部
  useEffect(() => {
    setSelectedRowKeys(valueToArray(value))
  }, [value])

  // 处理选择变化
  const handleSelectChange = (selectedKeys: string[]) => {
    setSelectedRowKeys(selectedKeys)
    if (onChange) {
      // 为了向后兼容，返回逗号分隔的字符串
      onChange(selectedKeys.join(','))
    }
  }

  // 全选/取消全选
  const handleSelectAll = () => {
    if (selectedRowKeys.length === filteredFiles.length) {
      // 取消全选
      handleSelectChange([])
    } else {
      // 全选
      const allIds = filteredFiles.map(file => file.id)
      handleSelectChange(allIds)
    }
  }

  // 格式化文件大小
  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  // 状态标签
  const statusTag = (status: string) => {
    const map: Record<string, { color: string, label: string }> = {
      'CLEAN_FINISH': { color: 'success', label: '已处理' },
      'CLEAN_PROCESSING': { color: 'processing', label: '处理中' },
      'CLEAN_FAILED': { color: 'error', label: '处理失败' },
      'UPLOAD_FAILED': { color: 'warning', label: '上传失败' },
      'UPLOAD_SUCCESS': { color: 'default', label: '已上传' },
    }
    const cfg = map[status] || { color: 'default', label: status }
    return <Tag color={cfg.color}>{cfg.label}</Tag>
  }

  // 文件类型标签
  const fileTypeTag = (fileType: string) => {
    const map: Record<string, { color: string, label: string }> = {
      'html': { color: 'blue', label: 'HTML' },
      'pdf': { color: 'red', label: 'PDF' },
      'docx': { color: 'green', label: 'DOCX' },
      'md': { color: 'purple', label: 'Markdown' },
    }
    const cfg = map[fileType.toLowerCase()] || { color: 'default', label: fileType }
    return <Tag color={cfg.color}>{cfg.label}</Tag>
  }

  // 搜索过滤
  const filteredFiles = files.filter(file =>
    file.file_name.toLowerCase().includes(searchText.toLowerCase()) ||
    file.id.toLowerCase().includes(searchText.toLowerCase())
  )

  // 分页数据
  const startIndex = (pagination.current - 1) * pagination.pageSize
  const endIndex = startIndex + pagination.pageSize
  const pageData = filteredFiles.slice(startIndex, endIndex)

  const columns = [
    {
      title: (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span>选择</span>
          {filteredFiles.length > 0 && (
            <Button
              size="small"
              type="link"
              onClick={handleSelectAll}
              style={{ padding: 0, height: 'auto' }}
            >
              {selectedRowKeys.length === filteredFiles.length ? '取消全选' : '全选'}
            </Button>
          )}
        </div>
      ),
      key: 'selection',
      width: 80,
      render: (_: any, record: FileItem) => (
        <input
          type="checkbox"
          checked={selectedRowKeys.includes(record.id)}
          onChange={(e) => {
            const newSelectedKeys = e.target.checked
              ? [...selectedRowKeys, record.id]
              : selectedRowKeys.filter(key => key !== record.id)
            handleSelectChange(newSelectedKeys)
          }}
          disabled={disabled}
        />
      ),
    },
    {
      title: '文件名',
      dataIndex: 'file_name',
      key: 'file_name',
      ellipsis: true,
      width: 200,
      render: (text: string) => (
        <Text strong style={{ fontSize: 13 }}>{text}</Text>
      ),
    },
    {
      title: '类型',
      dataIndex: 'file_type',
      key: 'file_type',
      width: 80,
      render: (type: string) => fileTypeTag(type),
    },
    {
      title: '大小',
      dataIndex: 'file_bytes',
      key: 'file_bytes',
      width: 90,
      render: (bytes: number) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {formatFileSize(bytes)}
        </Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'file_clean_status',
      key: 'file_clean_status',
      width: 90,
      render: (status: string) => statusTag(status),
    },
    {
      title: '创建时间',
      dataIndex: 'create_time',
      key: 'create_time',
      width: 120,
      render: (time: string) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {time ? time.slice(0, 10) : '-'}
        </Text>
      ),
    },
  ]

  return (
    <div style={{ border: '1px solid #d9d9d9', borderRadius: 6, padding: 16 }}>
      {/* 工具栏 */}
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space>
          <Input
            placeholder="搜索文件名或ID"
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            style={{ width: 200 }}
            disabled={disabled || !orgId}
          />
          <Button
            icon={<ReloadOutlined />}
            onClick={() => loadFiles()}
            loading={loading}
            disabled={disabled || !orgId}
          >
            刷新
          </Button>
        </Space>

        <div>
          <Text type="secondary" style={{ fontSize: 12, marginRight: 8 }}>
            共 {filteredFiles.length} 个文件
          </Text>
          <Tag color="blue">
            <CheckCircleOutlined /> 已选择 {selectedRowKeys.length} 个
          </Tag>
        </div>
      </div>

      {/* 文件列表表格 */}
      <Table
        size="small"
        rowKey="id"
        columns={columns}
        dataSource={pageData}
        loading={loading}
        pagination={false}
        scroll={{ y: 300 }}
        rowSelection={{
          selectedRowKeys,
          onChange: (selectedKeys) => handleSelectChange(selectedKeys as string[]),
          getCheckboxProps: () => ({ disabled }),
        }}
        rowClassName={(record) => selectedRowKeys.includes(record.id) ? 'ant-table-row-selected' : ''}
      />

      {/* 分页 */}
      {filteredFiles.length > pagination.pageSize && (
        <div style={{ marginTop: 16, display: 'flex', justifyContent: 'flex-end' }}>
          <Pagination
            size="small"
            current={pagination.current}
            pageSize={pagination.pageSize}
            total={filteredFiles.length}
            onChange={(page, pageSize) => {
              setPagination({ ...pagination, current: page, pageSize })
            }}
            showSizeChanger
            pageSizeOptions={['10', '20', '50', '100']}
            showTotal={(total) => `共 ${total} 个文件`}
          />
        </div>
      )}

      {/* 空状态 */}
      {!loading && filteredFiles.length === 0 && (
        <div style={{ textAlign: 'center', padding: '40px 0', color: '#999' }}>
          {orgId && orgId.length >= 8 ? '暂无文件数据' : '请输入组织ID查询文件'}
        </div>
      )}
    </div>
  )
}

export default DagentFileSelector