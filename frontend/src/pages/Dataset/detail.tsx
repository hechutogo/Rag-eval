import React, { useEffect, useState, useRef, useCallback } from 'react'
import { Table, Button, Modal, Form, Input, Select, Tag, Space, message, Descriptions, Progress, Checkbox, Tooltip, Alert } from 'antd'
import { PlusOutlined, ThunderboltOutlined, SearchOutlined, ReloadOutlined } from '@ant-design/icons'
import { useParams, useNavigate } from 'react-router-dom'
import { datasetApi, configApi } from '../../services/api'

const { Option } = Select

export default function DatasetDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [dataset, setDataset] = useState<any>(null)
  const [samples, setSamples] = useState<any[]>([])
  const [addModal, setAddModal] = useState(false)
  const [genModal, setGenModal] = useState(false)
  const [platforms, setPlatforms] = useState<any[]>([])
  const [judges, setJudges] = useState<any[]>([])
  const [form] = Form.useForm()
  const [genForm] = Form.useForm()

  // Chunk preview state
  const [chunks, setChunks] = useState<any[]>([])
  const [chunksLoading, setChunksLoading] = useState(false)
  const [selectedChunkIds, setSelectedChunkIds] = useState<string[]>([])

  // Generate progress state
  const [genTaskId, setGenTaskId] = useState<string | null>(null)
  const [genProgress, setGenProgress] = useState<{ progress: number; total: number; status: string } | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = async () => {
    const res = await datasetApi.get(id!) as any
    setDataset(res.data)
    setSamples(res.data?.samples || [])
  }

  useEffect(() => {
    load()
    configApi.listPlatforms().then((r: any) => setPlatforms(r.data || []))
    configApi.listJudges().then((r: any) => setJudges(r.data || []))
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [id])

  // Fetch chunks when platform + hub_id are both set
  const fetchChunks = useCallback(async () => {
    const platformId = genForm.getFieldValue('platform_config_id')
    const hubId = genForm.getFieldValue('knowledge_hub_id')
    if (!platformId || !hubId) {
      message.warning('请先选择平台配置并填写知识库 ID')
      return
    }
    setChunksLoading(true)
    setChunks([])
    setSelectedChunkIds([])
    try {
      const res = await datasetApi.chunksPreview(platformId, hubId) as any
      const data = res.data || []
      setChunks(data)
      setSelectedChunkIds(data.map((c: any) => c.id))
      if (data.length === 0) {
        message.info('未找到切片，请检查知识库 ID 是否正确')
      }
    } catch {
      message.error('获取切片失败')
    } finally {
      setChunksLoading(false)
    }
  }, [genForm])

  // Poll generate progress
  const startPolling = useCallback((taskId: string) => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const res = await datasetApi.getGenerateProgress(taskId) as any
        const data = res.data
        setGenProgress({ progress: data.progress || 0, total: data.total || 0, status: data.status })
        if (data.status === 'done' || data.status === 'failed') {
          if (pollRef.current) clearInterval(pollRef.current)
          pollRef.current = null
          if (data.status === 'done') {
            message.success('样本生成完成')
            load()
          } else {
            message.error(`生成失败: ${data.error_message || '未知错误'}`)
          }
        }
      } catch {
        // ignore poll errors
      }
    }, 2000)
  }, [])

  const addSample = async () => {
    const vals = await form.validateFields()
    await datasetApi.addSample({
      ...vals,
      dataset_id: id,
      relevant_chunk_ids: vals.relevant_chunk_ids
        ? vals.relevant_chunk_ids.split('\n').map((s: string) => s.trim()).filter(Boolean)
        : [],
    })
    message.success('样本已添加')
    setAddModal(false)
    form.resetFields()
    load()
  }

  const startGenerate = async () => {
    const vals = await genForm.validateFields()
    if (selectedChunkIds.length === 0 && chunks.length > 0) {
      message.warning('请至少选择一个切片')
      return
    }
    // Derive file_id_list from selected chunks
    const fileIds = [...new Set(
      chunks.filter(c => selectedChunkIds.includes(c.id)).map((c: any) => c.file_id)
    )]
    const res = await datasetApi.generate({
      ...vals,
      dataset_id: id,
      file_id_list: fileIds.length > 0 ? fileIds : [vals.knowledge_hub_id],
      chunk_ids: selectedChunkIds,
    }) as any
    const taskId = res.data?.gen_task_id
    if (taskId) {
      setGenTaskId(taskId)
      setGenProgress({ progress: 0, total: selectedChunkIds.length || 0, status: 'pending' })
      startPolling(taskId)
      message.success('生成任务已启动')
    }
  }

  const closeGenModal = () => {
    setGenModal(false)
    setChunks([])
    setSelectedChunkIds([])
    setGenTaskId(null)
    setGenProgress(null)
    genForm.resetFields()
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  const columns = [
    { title: '问题', dataIndex: 'question', ellipsis: true, width: '30%' },
    { title: '参考答案', dataIndex: 'reference_answer', ellipsis: true, width: '30%' },
    { title: '知识库 ID', dataIndex: 'knowledge_hub_id', ellipsis: true },
    {
      title: '类型', dataIndex: 'metadata',
      render: (m: any) => m?.type ? <Tag>{m.type}</Tag> : '-'
    },
    {
      title: '难度', dataIndex: 'metadata',
      key: 'difficulty',
      render: (m: any) => {
        const color: any = { easy: 'green', medium: 'orange', hard: 'red' }
        return m?.difficulty ? <Tag color={color[m.difficulty]}>{m.difficulty}</Tag> : '-'
      }
    },
  ]

  const chunkColumns = [
    {
      title: () => (
        <Checkbox
          checked={selectedChunkIds.length === chunks.length && chunks.length > 0}
          indeterminate={selectedChunkIds.length > 0 && selectedChunkIds.length < chunks.length}
          onChange={e => setSelectedChunkIds(e.target.checked ? chunks.map(c => c.id) : [])}
        />
      ),
      dataIndex: 'id',
      width: 40,
      render: (cid: string) => (
        <Checkbox
          checked={selectedChunkIds.includes(cid)}
          onChange={e => {
            setSelectedChunkIds(prev =>
              e.target.checked ? [...prev, cid] : prev.filter(x => x !== cid)
            )
          }}
        />
      ),
    },
    {
      title: '切片内容',
      dataIndex: 'content',
      ellipsis: true,
      render: (text: string) => (
        <Tooltip title={text} placement="topLeft" overlayStyle={{ maxWidth: 500 }}>
          <span>{text?.slice(0, 120)}{text?.length > 120 ? '...' : ''}</span>
        </Tooltip>
      ),
    },
    { title: '文件 ID', dataIndex: 'file_id', ellipsis: true, width: 120 },
  ]

  const isGenerating = genProgress && (genProgress.status === 'pending' || genProgress.status === 'running')

  return (
    <div>
      <Button type="link" onClick={() => navigate('/dataset')} style={{ paddingLeft: 0 }}>← 返回列表</Button>
      {dataset && (
        <Descriptions title={dataset.name} bordered size="small" style={{ marginBottom: 16 }}>
          <Descriptions.Item label="描述">{dataset.description || '-'}</Descriptions.Item>
          <Descriptions.Item label="样本数">{dataset.sample_count}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{dataset.created_at?.slice(0, 19)}</Descriptions.Item>
        </Descriptions>
      )}

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginBottom: 12 }}>
        <Button icon={<ThunderboltOutlined />} onClick={() => setGenModal(true)}>LLM 自动生成</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddModal(true)}>手动添加样本</Button>
      </div>

      <Table rowKey="id" dataSource={samples} columns={columns} size="small" />

      {/* Add sample modal */}
      <Modal title="添加样本" open={addModal} onOk={addSample} onCancel={() => setAddModal(false)} width={600}>
        <Form form={form} layout="vertical">
          <Form.Item name="question" label="问题" rules={[{ required: true }]}>
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="reference_answer" label="参考答案" rules={[{ required: true }]}>
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="knowledge_hub_id" label="知识库 ID" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="relevant_chunk_ids" label="相关 Chunk IDs（每行一个）">
            <Input.TextArea rows={3} placeholder="chunk_id_1&#10;chunk_id_2" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Generate modal */}
      <Modal
        title="LLM 自动生成样本"
        open={genModal}
        onCancel={closeGenModal}
        width={800}
        footer={
          isGenerating ? null : [
            <Button key="cancel" onClick={closeGenModal}>取消</Button>,
            <Button key="ok" type="primary" onClick={startGenerate}
              disabled={chunks.length > 0 && selectedChunkIds.length === 0}>
              开始生成
            </Button>,
          ]
        }
      >
        {/* Progress bar */}
        {genProgress && (
          <div style={{ marginBottom: 16 }}>
            <Alert
              type={genProgress.status === 'done' ? 'success' : genProgress.status === 'failed' ? 'error' : 'info'}
              message={
                genProgress.status === 'done' ? '生成完成' :
                genProgress.status === 'failed' ? '生成失败' :
                `正在生成中... (${genProgress.progress}/${genProgress.total})`
              }
              showIcon
            />
            <Progress
              percent={genProgress.total > 0 ? Math.round(genProgress.progress / genProgress.total * 100) : 0}
              status={genProgress.status === 'failed' ? 'exception' : genProgress.status === 'done' ? 'success' : 'active'}
              style={{ marginTop: 8 }}
            />
            {genProgress.status === 'done' && (
              <Button type="link" onClick={() => { closeGenModal(); load() }}>关闭并刷新</Button>
            )}
          </div>
        )}

        {!isGenerating && (
          <Form form={genForm} layout="vertical">
            <Form.Item name="platform_config_id" label="平台配置" rules={[{ required: true }]}>
              <Select placeholder="选择平台">
                {platforms.map((p: any) => <Option key={p.id} value={p.id}>{p.name}</Option>)}
              </Select>
            </Form.Item>
            <Form.Item name="judge_config_id" label="Judge 模型" rules={[{ required: true }]}>
              <Select placeholder="选择 Judge">
                {judges.map((j: any) => <Option key={j.id} value={j.id}>{j.name} ({j.model})</Option>)}
              </Select>
            </Form.Item>
            <Form.Item name="knowledge_hub_id" label="知识库 ID" rules={[{ required: true }]}>
              <Space.Compact style={{ width: '100%' }}>
                <Form.Item name="knowledge_hub_id" noStyle rules={[{ required: true }]}>
                  <Input style={{ flex: 1 }} placeholder="输入知识库 ID" />
                </Form.Item>
                <Button icon={<SearchOutlined />} loading={chunksLoading} onClick={fetchChunks}>
                  加载切片
                </Button>
              </Space.Compact>
            </Form.Item>

            {/* Chunk preview table */}
            {chunks.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <span>共 {chunks.length} 个切片，已选 {selectedChunkIds.length} 个</span>
                  <Button size="small" icon={<ReloadOutlined />} onClick={fetchChunks}>刷新</Button>
                </div>
                <Table
                  rowKey="id"
                  dataSource={chunks}
                  columns={chunkColumns}
                  size="small"
                  pagination={{ pageSize: 5, size: 'small' }}
                  scroll={{ y: 240 }}
                />
              </div>
            )}

            <Form.Item name="questions_per_chunk" label="每个切片生成问题数" initialValue={2}>
              <Select>
                {[1, 2, 3, 4].map(n => <Option key={n} value={n}>{n}</Option>)}
              </Select>
            </Form.Item>
          </Form>
        )}
      </Modal>
    </div>
  )
}
