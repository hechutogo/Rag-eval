import React, { useState, useEffect } from 'react'
import { Tree, Card, Tag, Space, Typography, Button, Input, message } from 'antd'
import { ReloadOutlined, FolderOutlined, FileOutlined, FileTextOutlined, ClusterOutlined } from '@ant-design/icons'
import { qaGenApi } from '../../services/api'

const { Text } = Typography
const { Search } = Input

interface TreeNode {
  key: string
  title: string
  type: 'major_chapter' | 'minor_chapter' | 'file' | 'chunk'
  file_id?: string
  chunk_id?: string
  chunk_count?: number
  file_type?: string
  status?: string
  preview?: string
  has_image?: boolean
  children?: TreeNode[]
}

interface DagentTreeSelectorProps {
  orgId: string
  envUrl?: string
  value?: string[] // 选中的文件ID列表
  onChange?: (fileIds: string[]) => void
  disabled?: boolean
}

const DagentTreeSelector: React.FC<DagentTreeSelectorProps> = ({
  orgId,
  envUrl = '',
  value = [],
  onChange,
  disabled = false,
}) => {
  const [treeData, setTreeData] = useState<TreeNode[]>([])
  const [loading, setLoading] = useState(false)
  const [expandedKeys, setExpandedKeys] = useState<string[]>([])
  const [checkedKeys, setCheckedKeys] = useState<string[]>([])
  const [searchText, setSearchText] = useState('')

  // 加载树形数据
  const loadTreeData = async () => {
    if (!orgId || orgId.length < 8) return

    setLoading(true)
    try {
      const res: any = await qaGenApi.getDagentTree(orgId, envUrl)
      if (res.status === 0) {
        setTreeData(res.data || [])
        // 默认展开第一级
        if (res.data && res.data.length > 0) {
          setExpandedKeys(res.data.map((n: TreeNode) => n.key))
        }
      } else {
        message.error(res.message || '加载树形数据失败')
      }
    } catch (e: any) {
      console.error('加载树形数据失败:', e)
      message.error(`加载失败: ${e.message || '未知错误'}`)
    } finally {
      setLoading(false)
    }
  }

  // 初始化加载
  useEffect(() => {
    if (orgId && orgId.length >= 8) {
      loadTreeData()
    } else {
      setTreeData([])
    }
  }, [orgId, envUrl])

  // 同步选中状态到外部
  useEffect(() => {
    if (value) {
      // 将 file:id 格式转换为 key 格式
      const keys = value.map(id => `file:${id}`)
      setCheckedKeys(keys)
    }
  }, [value])

  // 获取所有子文件key
  const getAllFileKeys = (node: TreeNode): string[] => {
    const keys: string[] = []
    if (node.type === 'file' && node.file_id) {
      keys.push(node.key)
    }
    if (node.children) {
      node.children.forEach(child => {
        keys.push(...getAllFileKeys(child))
      })
    }
    return keys
  }

  // 处理选择变化
  const handleCheck = (checked: any, info: any) => {
    const keys = checked as string[]
    setCheckedKeys(keys)

    // 提取文件ID
    const fileIds: string[] = []
    keys.forEach((key: string) => {
      if (key.startsWith('file:')) {
        fileIds.push(key.replace('file:', ''))
      } else if (key.startsWith('major:') || key.startsWith('minor:')) {
        // 如果是章节被选中，获取其下所有文件
        const findNode = (nodes: TreeNode[], targetKey: string): TreeNode | null => {
          for (const node of nodes) {
            if (node.key === targetKey) return node
            if (node.children) {
              const found = findNode(node.children, targetKey)
              if (found) return found
            }
          }
          return null
        }
        const node = findNode(treeData, key)
        if (node) {
          const fileKeys = getAllFileKeys(node)
          fileKeys.forEach(k => fileIds.push(k.replace('file:', '')))
        }
      }
    })

    // 去重
    const uniqueFileIds = [...new Set(fileIds)]
    onChange?.(uniqueFileIds)
  }

  // 搜索过滤树
  const filterTreeData = (data: TreeNode[], search: string): TreeNode[] => {
    if (!search) return data

    return data.map(node => {
      const filteredChildren = node.children ? filterTreeData(node.children, search) : []
      const matchTitle = node.title.toLowerCase().includes(search.toLowerCase())

      if (matchTitle || filteredChildren.length > 0) {
        return {
          ...node,
          children: filteredChildren
        }
      }
      return null
    }).filter(Boolean) as TreeNode[]
  }

  // 自定义标题渲染
  const titleRender = (nodeData: TreeNode) => {
    const { type, title, chunk_count, file_type, status, preview, has_image } = nodeData

    const getIcon = () => {
      switch (type) {
        case 'major_chapter':
          return <ClusterOutlined style={{ color: '#1890ff', marginRight: 4 }} />
        case 'minor_chapter':
          return <FolderOutlined style={{ color: '#faad14', marginRight: 4 }} />
        case 'file':
          return <FileTextOutlined style={{ color: '#52c41a', marginRight: 4 }} />
        case 'chunk':
          return <FileOutlined style={{ color: '#722ed1', marginRight: 4, fontSize: 12 }} />
        default:
          return null
      }
    }

    const getTag = () => {
      if (type === 'file') {
        const color = status === 'clean_finish' ? 'success' : status === 'clean_processing' ? 'processing' : 'default'
        return (
          <Space size={4}>
            <Tag color="blue">{file_type?.toUpperCase() || 'FILE'}</Tag>
            {chunk_count !== undefined && <Tag color="cyan">{chunk_count} 切片</Tag>}
          </Space>
        )
      }
      if (type === 'chunk' && has_image) {
        return <Tag color="orange">含图片</Tag>
      }
      return null
    }

    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        {getIcon()}
        <Text
          style={{
            fontSize: type === 'chunk' ? 12 : 13,
            fontWeight: type === 'major_chapter' ? 600 : type === 'minor_chapter' ? 500 : 'normal'
          }}
        >
          {title}
        </Text>
        {getTag()}
        {type === 'chunk' && preview && (
          <Text type="secondary" style={{ fontSize: 11, marginLeft: 8 }}>
            {preview}
          </Text>
        )}
      </span>
    )
  }

  // 统计信息
  const getStats = () => {
    const stats = { files: 0, chunks: 0, selectedFiles: 0 }

    const traverse = (nodes: TreeNode[]) => {
      nodes.forEach(node => {
        if (node.type === 'file') {
          stats.files++
          stats.chunks += node.chunk_count || 0
          if (checkedKeys.includes(node.key)) {
            stats.selectedFiles++
          }
        }
        if (node.children) traverse(node.children)
      })
    }

    traverse(treeData)
    return stats
  }

  const stats = getStats()
  const filteredTreeData = searchText ? filterTreeData(treeData, searchText) : treeData

  return (
    <Card
      size="small"
      loading={loading}
      title={
        <Space>
          <span>知识库文件树</span>
          <Tag color="blue">{stats.files} 文件</Tag>
          <Tag color="cyan">{stats.chunks} 切片</Tag>
          <Tag color="green">已选 {stats.selectedFiles} 文件</Tag>
        </Space>
      }
      extra={
        <Space>
          <Search
            placeholder="搜索文件或章节"
            allowClear
            size="small"
            style={{ width: 180 }}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
          />
          <Button
            icon={<ReloadOutlined />}
            size="small"
            onClick={loadTreeData}
            loading={loading}
            disabled={disabled || !orgId}
          >
            刷新
          </Button>
        </Space>
      }
    >
      {treeData.length > 0 ? (
        <Tree
          checkable
          checkStrictly={false}
          checkedKeys={checkedKeys}
          expandedKeys={expandedKeys}
          onExpand={(keys) => setExpandedKeys(keys as string[])}
          onCheck={handleCheck}
          treeData={filteredTreeData}
          titleRender={titleRender}
          style={{ maxHeight: 400, overflow: 'auto' }}
          disabled={disabled}
        />
      ) : (
        <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>
          {orgId && orgId.length >= 8 ? '暂无数据，请刷新重试' : '请输入组织ID'}
        </div>
      )}
    </Card>
  )
}

export default DagentTreeSelector
