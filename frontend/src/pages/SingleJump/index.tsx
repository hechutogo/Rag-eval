import React, { useEffect, useState, useRef } from 'react'
import {
  Table, Button, Modal, Form, Input, InputNumber, Switch, Upload,
  message, Popconfirm, Tag, Space, Progress, Tooltip, Drawer,
  Row, Col, Card, Statistic, Divider, Typography, Empty, Spin, Select
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, EyeOutlined, ReloadOutlined,
  UploadOutlined, QuestionCircleOutlined, CheckCircleOutlined,
  CloseCircleOutlined, WarningOutlined, DownloadOutlined
} from '@ant-design/icons'
import { singleJumpApi, multiHopApi } from '../../services/api'

const { Text, Paragraph } = Typography

// ── 指标说明 ──────────────────────────────────────────────────────────────────
const METRIC_TIPS: Record<string, string> = {
  recall_rate: '有召回结果的问题数 / 总问题数。越高说明知识库覆盖越全面。',
  file_hit_rate: '召回结果中包含预期文件的问题数 / 有召回结果的问题数。越高说明单跳定位越准确。',
  avg_cosine_sim: '召回结果与问题的平均余弦相似度（0~1）。越高说明语义匹配越好。',
  avg_latency_ms: '每次召回的平均耗时（毫秒）。',
  section_match_rate: '成功映射到知识库文件的章节数 / 总章节数。',
}

function MetricTip({ metricKey }: { metricKey: string }) {
  return METRIC_TIPS[metricKey] ? (
    <Tooltip title={METRIC_TIPS[metricKey]}>
      <QuestionCircleOutlined style={{ marginLeft: 4, color: '#999', fontSize: 12 }} />
    </Tooltip>
  ) : null
}

// ── 状态标签 ──────────────────────────────────────────────────────────────────
function StatusTag({ status }: { status: string }) {
  const map: Record<string, { color: string; label: string }> = {
    pending: { color: 'default', label: '等待中' },
    running: { color: 'processing', label: '运行中' },
    done: { color: 'success', label: '完成' },
    failed: { color: 'error', label: '失败' },
  }
  const cfg = map[status] || { color: 'default', label: status }
  return <Tag color={cfg.color}>{cfg.label}</Tag>
}

// ── 汇总卡片 ──────────────────────────────────────────────────────────────────
function SummaryCards({ summary }: { summary: any }) {
  const pct = (v: number | null) => v != null ? `${(v * 100).toFixed(1)}%` : 'N/A'
  const cards = [
    { key: 'recall_rate', label: '召回率', value: pct(summary.recall_rate), color: summary.recall_rate >= 0.8 ? '#52c41a' : '#faad14' },
    { key: 'file_hit_rate', label: '文件命中率', value: pct(summary.file_hit_rate), color: summary.file_hit_rate >= 0.7 ? '#52c41a' : '#faad14' },
    { key: 'avg_cosine_sim', label: '平均余弦相似度', value: summary.avg_cosine_sim != null ? summary.avg_cosine_sim.toFixed(4) : 'N/A', color: '#1677ff' },
    { key: 'avg_latency_ms', label: '平均延迟', value: summary.avg_latency_ms != null ? `${summary.avg_latency_ms.toFixed(0)}ms` : 'N/A', color: '#722ed1' },
    { key: 'section_match_rate', label: '章节匹配率', value: summary.total_sections ? `${summary.matched_sections}/${summary.total_sections}` : 'N/A', color: '#13c2c2' },
  ]
  return (
    <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
      {cards.map(c => (
        <Col key={c.key} xs={12} sm={8} md={6} lg={4}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 22, fontWeight: 600, color: c.color }}>{c.value}</div>
            <div style={{ fontSize: 12, color: '#666', marginTop: 4 }}>
              {c.label}<MetricTip metricKey={c.key} />
            </div>
          </Card>
        </Col>
      ))}
      <Col xs={12} sm={8} md={6} lg={4}>
        <Card size="small" style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 22, fontWeight: 600 }}>{summary.total_questions ?? '-'}</div>
          <div style={{ fontSize: 12, color: '#666', marginTop: 4 }}>总问题数</div>
        </Card>
      </Col>
    </Row>
  )
}

// ── 主页面 ────────────────────────────────────────────────────────────────────
export default function SingleJump() {
  const [tasks, setTasks] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [createModal, setCreateModal] = useState(false)
  const [form] = Form.useForm()
  const [fileList, setFileList] = useState<any[]>([])
  const [folderFiles, setFolderFiles] = useState<any[]>([])
  const [submitting, setSubmitting] = useState(false)
  const mergedFileRef = useRef<File | null>(null)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])

  // 报告抽屉
  const [reportDrawer, setReportDrawer] = useState<string | null>(null)
  const [summary, setSummary] = useState<any>(null)
  const [sections, setSections] = useState<any[]>([])
  const [selectedSection, setSelectedSection] = useState<string | null>(null)
  const [results, setResults] = useState<any[]>([])
  const [resultLoading, setResultLoading] = useState(false)
  const [detailDrawer, setDetailDrawer] = useState<any>(null)
  const [agentIdForRecall, setAgentIdForRecall] = useState('')
  const [agentRecallLoading, setAgentRecallLoading] = useState(false)
  const [agentRecallItems, setAgentRecallItems] = useState<any[]>([])
  const [agentOptions, setAgentOptions] = useState<{ label: string; value: string }[]>([])
  const [agentOptionsLoading, setAgentOptionsLoading] = useState(false)
  // 创建任务时的 agent 选项
  const [createAgentOptions, setCreateAgentOptions] = useState<{ label: string; value: string }[]>([])
  const [createAgentOptionsLoading, setCreateAgentOptionsLoading] = useState(false)
  const orgIdValue = Form.useWatch('org_id', form)
  const envUrlValue = Form.useWatch('env_url', form)

  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const loadTasks = async () => {
    setLoading(true)
    try {
      const res = await singleJumpApi.listTasks() as any
      setTasks(res.data || [])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadTasks()
    pollingRef.current = setInterval(() => {
      setTasks(prev => {
        const hasRunning = prev.some(t => t.status === 'running' || t.status === 'pending')
        if (hasRunning) loadTasks()
        return prev
      })
    }, 3000)
    return () => { if (pollingRef.current) clearInterval(pollingRef.current) }
  }, [])

  const handleCreate = async () => {
    const vals = await form.validateFields()
    if (!fileList.length && !mergedFileRef.current) {
      message.error('请上传问答集文件或选择文件夹');
      return
    }
    setSubmitting(true)
    try {
      const fd = new FormData()

      // 文件夹场景用合并后的文件，单文件场景用原始文件
      const uploadFile = mergedFileRef.current || fileList[0].originFileObj
      fd.append('file', uploadFile)
      fd.append('name', vals.name || (folderFiles.length > 0 ? `批量任务(${folderFiles.length}个文件)` : ''))
      fd.append('env_url', vals.env_url)
      fd.append('org_id', vals.org_id)
      fd.append('d_user_id', vals.d_user_id || 'test')
      fd.append('agent_id', vals.agent_id || '')
      fd.append('top_k', String(vals.top_k ?? 64))
      fd.append('recall_top_k', String(vals.recall_top_k ?? 64))
      fd.append('concurrency', String(vals.concurrency ?? 5))
      fd.append('cross_chunk', String(vals.cross_chunk ?? true))

      await singleJumpApi.createTask(fd)

      message.success('任务已创建，正在后台运行')
      setCreateModal(false)
      form.resetFields()
      setFileList([])
      setFolderFiles([])
      mergedFileRef.current = null
      loadTasks()
    } catch (e: any) {
      message.error(e?.message || '创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleFolderSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    const mdFiles = files.filter(f => f.name.endsWith('.md'))
    if (mdFiles.length === 0) {
      message.warning('文件夹中没有 MD 文件')
      return
    }
    // 前端并行读取所有文件内容，合并为单个 File，避免多 part 上传慢
    const texts = await Promise.all(mdFiles.map(f => f.text()))
    const merged = new File([texts.join('\n')], `batch_${mdFiles.length}files.md`, { type: 'text/markdown' })
    mergedFileRef.current = merged
    setFolderFiles(mdFiles)
    setFileList([])
    message.success(`已选择 ${mdFiles.length} 个 MD 文件，将合并为单个文件上传`)
  }

  // ── 批量删除 ────────────────────────────────────────────────────────────────
  const handleBatchDelete = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要删除的任务')
      return
    }
    Modal.confirm({
      title: `确认删除选中的 ${selectedRowKeys.length} 个任务？`,
      content: '删除后将无法恢复，相关测试结果也会被删除。',
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      async onOk() {
        try {
          await Promise.all(selectedRowKeys.map(id => singleJumpApi.deleteTask(id as string)))
          message.success(`成功删除 ${selectedRowKeys.length} 个任务`)
          setSelectedRowKeys([])
          loadTasks()
        } catch (e: any) {
          message.error(e?.message || '批量删除失败')
        }
      },
    })
  }

  const handleExportFailed = () => {
    if (!reportDrawer) return
    const url = singleJumpApi.exportFailedMd(reportDrawer)
    window.open(url, '_blank')
  }

  const handleExportFileMiss = () => {
    if (!reportDrawer) return
    const url = singleJumpApi.exportFileMissMd(reportDrawer)
    window.open(url, '_blank')
  }

  const openReport = async (taskId: string) => {
    setReportDrawer(taskId)
    setSummary(null)
    setSections([])
    setSelectedSection(null)
    setResults([])
    try {
      const [sumRes, secRes] = await Promise.all([
        singleJumpApi.getSummary(taskId) as any,
        singleJumpApi.getSections(taskId) as any,
      ])
      setSummary(sumRes.data)
      setSections(secRes.data || [])
    } catch (e: any) {
      setReportDrawer(null)
      message.error(e?.response?.data?.detail || e?.message || '加载测试报告失败')
    }
  }

  const loadResults = async (taskId: string, section: string | null) => {
    setResultLoading(true)
    try {
      const res = await singleJumpApi.getResults(taskId, section || undefined) as any
      setResults(res.data || [])
    } finally {
      setResultLoading(false)
    }
  }

  const handleSectionChange = (val: string | null) => {
    setSelectedSection(val)
    if (reportDrawer) loadResults(reportDrawer, val)
  }

  const openDetail = (row: any) => {
    setDetailDrawer(row)
    setAgentRecallItems([])
    if (reportDrawer) loadAgentOptions(reportDrawer)
  }

  const loadAgentOptions = async (taskId: string) => {
    setAgentOptionsLoading(true)
    try {
      const res = await singleJumpApi.listAgents(taskId) as any
      const opts = (res?.data || []).map((a: any) => ({ label: `${a.name} (${a.id.slice(0, 8)}...)`, value: a.id }))
      setAgentOptions(opts)
    } catch {
      setAgentOptions([])
    } finally {
      setAgentOptionsLoading(false)
    }
  }

  const loadAgentRecall = async () => {
    if (!reportDrawer || !detailDrawer?.id) return
    if (!agentIdForRecall.trim()) {
      message.warning('请先填写 Agent ID')
      return
    }
    setAgentRecallLoading(true)
    try {
      const res = await singleJumpApi.getAgentRecall(reportDrawer, detailDrawer.id, agentIdForRecall.trim()) as any
      setAgentRecallItems(res?.data?.items || [])
      message.success(`已拉取 ${res?.data?.items?.length || 0} 条在线 Agent 召回结果`)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || e?.message || '拉取在线 Agent 召回失败')
    } finally {
      setAgentRecallLoading(false)
    }
  }

  // 加载创建任务时的 agent 列表
  const loadCreateAgentOptions = async () => {
    if (!orgIdValue || !envUrlValue) return
    setCreateAgentOptionsLoading(true)
    try {
      const res = await multiHopApi.listDagentAgents(envUrlValue, orgIdValue) as any
      const opts = (res?.data || []).map((a: any) => ({ label: `${a.name} (${a.id.slice(0, 8)}...)`, value: a.id }))
      setCreateAgentOptions(opts)
    } catch {
      setCreateAgentOptions([])
    } finally {
      setCreateAgentOptionsLoading(false)
    }
  }

  // 当 org_id 或 env_url 变化时，加载 agent 列表
  useEffect(() => {
    if (orgIdValue && envUrlValue && createModal) {
      loadCreateAgentOptions()
    }
  }, [orgIdValue, envUrlValue, createModal])

  // ── 任务列表列 ──────────────────────────────────────────────────────────────
  const taskColumns = [
    { title: '任务名称', dataIndex: 'name', ellipsis: true, width: 180 },
    { title: '环境地址', dataIndex: 'env_url', ellipsis: true },
    { title: 'Org ID', dataIndex: 'org_id', ellipsis: true, width: 160,
      render: (v: string) => <Text code style={{ fontSize: 11 }}>{v?.slice(0, 16)}…</Text> },
    { title: '状态', dataIndex: 'status', width: 90, render: (v: string) => <StatusTag status={v} /> },
    {
      title: '进度', width: 140,
      render: (_: any, r: any) => r.status === 'running'
        ? <Progress percent={r.total ? Math.round(r.progress / r.total * 100) : 0} size="small" />
        : r.status === 'done' ? <Text type="success">{r.total} 条完成</Text>
        : r.status === 'failed' ? <Tooltip title={r.error_message}><Text type="danger">失败</Text></Tooltip>
        : <Text type="secondary">-</Text>
    },
    { title: '创建时间', dataIndex: 'created_at', width: 160,
      render: (v: string) => v?.slice(0, 19) },
    {
      title: '操作', width: 120,
      render: (_: any, r: any) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} disabled={r.status !== 'done'}
            onClick={() => openReport(r.id)}>报告</Button>
          <Popconfirm title="确认删除？" onConfirm={async () => {
            await singleJumpApi.deleteTask(r.id)
            loadTasks()
          }}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      )
    },
  ]

  // ── 章节列表列 ──────────────────────────────────────────────────────────────
  const sectionColumns = [
    { title: '章节路径', dataIndex: 'section_path', ellipsis: true },
    { title: '对应文件', dataIndex: 'file_name', ellipsis: true,
      render: (v: string) => v
        ? <Tooltip title={v}><Text code style={{ fontSize: 11 }}>{v}</Text></Tooltip>
        : <Text type="secondary">未匹配</Text>
    },
    { title: '匹配方式', dataIndex: 'match_type', width: 90,
      render: (v: string) => v
        ? <Tag color={v === 'exact' ? 'green' : v === 'path_contains' ? 'blue' : v === 'basename' ? 'cyan' : 'orange'}>{v}</Tag>
        : <Tag color="red">未匹配</Tag>
    },
    { title: '问题数', dataIndex: 'total', width: 70 },
    { title: '召回数', dataIndex: 'recalled', width: 70,
      render: (v: number, r: any) => <Text type={v === r.total ? 'success' : 'warning'}>{v}</Text> },
    { title: '文件命中', dataIndex: 'file_hits', width: 80,
      render: (v: number, r: any) => r.recalled
        ? <Text type={v / r.recalled >= 0.7 ? 'success' : 'warning'}>{v}/{r.recalled}</Text>
        : '-'
    },
    { title: '平均相似度', dataIndex: 'avg_sim', width: 100,
      render: (v: number) => v != null ? v.toFixed(4) : '-' },
    {
      title: '操作', width: 80,
      render: (_: any, r: any) => (
        <Button size="small" type="link" onClick={() => handleSectionChange(r.section_path)}>
          查看问题
        </Button>
      )
    },
  ]

  // ── 问题结果列 ──────────────────────────────────────────────────────────────
  const resultColumns = [
    { title: 'ID', dataIndex: 'qid', width: 60 },
    { title: '问题', dataIndex: 'question', ellipsis: true },
    {
      title: '召回状态', width: 90,
      render: (_: any, r: any) => r.error
        ? <Tooltip title={r.error}><Tag color="red" icon={<CloseCircleOutlined />}>错误</Tag></Tooltip>
        : r.retrieved?.length
          ? <Tag color="green" icon={<CheckCircleOutlined />}>{r.retrieved.length} 条</Tag>
          : <Tag color="orange" icon={<WarningOutlined />}>空</Tag>
    },
    { title: '文件命中', dataIndex: 'is_file_hit', width: 80,
      render: (v: number, r: any) => !r.file_id ? <Text type="secondary">-</Text>
        : v ? <Tag color="green">命中</Tag> : <Tag color="orange">未命中</Tag>
    },
    {
      title: '切片命中', width: 200,
      render: (_: any, r: any) => {
        if (!r.expected_chunk_id) return <Text type="secondary">-</Text>
        const chunkName = r.expected_chunk_name || r.expected_chunk_id?.slice(0, 16) + '...'
        if (r.is_chunk_hit) {
          return <Tooltip title={chunkName}><Tag color="green">{chunkName.slice(0, 20)} 命中(Top{r.chunk_hit_rank})</Tag></Tooltip>
        }
        return <Tooltip title={chunkName}><Tag color="orange">{chunkName.slice(0, 20)} 未命中</Tag></Tooltip>
      }
    },
    { title: 'Top1召回文件', width: 180,
      render: (_: any, r: any) => {
        const top1 = r.retrieved?.[0]
        const fileName = top1?.display_file_name || top1?.file_name
        return fileName ? <Tooltip title={fileName}><Text code style={{ fontSize: 11 }}>{fileName}</Text></Tooltip> : <Text type="secondary">-</Text>
      }
    },
    { title: '最佳相似度', dataIndex: 'best_cosine_sim', width: 100,
      render: (v: number) => v != null
        ? <Text type={v >= 0.8 ? 'success' : v >= 0.6 ? 'warning' : 'danger'}>{v.toFixed(4)}</Text>
        : '-'
    },
    { title: '延迟', dataIndex: 'latency_ms', width: 70,
      render: (v: number) => v ? `${v}ms` : '-' },
    {
      title: '详情', width: 60,
      render: (_: any, r: any) => (
        <Button size="small" type="link" onClick={() => openDetail(r)}>查看</Button>
      )
    },
  ]

  return (
    <div>
      {/* 标题栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>单跳召回测试</Typography.Title>
        <Space>
          {selectedRowKeys.length > 0 && (
            <Button danger icon={<DeleteOutlined />} onClick={handleBatchDelete}>
              批量删除 ({selectedRowKeys.length})
            </Button>
          )}
          <Button icon={<ReloadOutlined />} onClick={loadTasks}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModal(true)}>新建测试</Button>
        </Space>
      </div>

      <Table
        rowKey="id"
        dataSource={tasks}
        columns={taskColumns}
        loading={loading}
        size="small"
        pagination={{ pageSize: 10 }}
        rowSelection={{
          selectedRowKeys,
          onChange: setSelectedRowKeys,
        }}
      />

      {/* 新建任务弹窗 */}
      <Modal
        title="新建单跳召回测试"
        open={createModal}
        onOk={handleCreate}
        onCancel={() => { setCreateModal(false); form.resetFields(); setFileList([]) }}
        confirmLoading={submitting}
        width={560}
      >
        <Form form={form} layout="vertical" initialValues={{ top_k: 64, recall_top_k: 64, concurrency: 20, cross_chunk: true, d_user_id: 'test' }}>
          <Form.Item name="name" label="任务名称">
            <Input placeholder="可选，默认使用文件名" />
          </Form.Item>
          <Form.Item name="env_url" label="Agent 环境地址" rules={[{ required: true }]}
            tooltip="dagent 服务地址，如 https://dagent.d-robotics.cc">
            <Input placeholder="https://dagent.d-robotics.cc" />
          </Form.Item>
          <Form.Item name="org_id" label="Org ID" rules={[{ required: true }]}
            tooltip="知识库所属的组织 ID">
            <Input placeholder="a4d49699ba313815..." />
          </Form.Item>
          <Form.Item name="agent_id" label="Agent（可选）"
            tooltip="选择要使用的 Agent 版本进行召回测试，为空时直接调用知识库搜索 API">
            <Select
              placeholder="请选择 Agent（可选）"
              allowClear
              showSearch
              options={createAgentOptions}
              loading={createAgentOptionsLoading}
              disabled={!orgIdValue || !envUrlValue}
              notFoundContent={!orgIdValue || !envUrlValue ? '请先填写 Org ID 和环境地址' : '未找到 Agent'}
            />
          </Form.Item>
          <Form.Item name="d_user_id" label="User ID"
            tooltip="请求头 d-user-id，默认 test">
            <Input />
          </Form.Item>
          <Row gutter={12}>
            <Col span={6}>
              <Form.Item name="top_k" label={<span>命中判断 Top K <MetricTip metricKey="recall_rate" /></span>}>
                <InputNumber min={1} max={200} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="recall_top_k" label={<span>召回数量 Top K <Tooltip title="调用召回API时请求的结果数量，建议设置较大值以获取更多召回切片用于分析"><QuestionCircleOutlined style={{ color: '#999' }} /></Tooltip></span>}>
                <InputNumber min={1} max={500} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="concurrency" label="并发数">
                <InputNumber min={1} max={50} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="cross_chunk" label={<span>跨切片模式 <Tooltip title="关闭后限定在对应文件内召回（当前 dagent 版本建议开启）"><QuestionCircleOutlined style={{ color: '#999' }} /></Tooltip></span>} valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="问答集文件（MD 格式）" required>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Space wrap>
                <Upload
                  accept=".md"
                  maxCount={1}
                  fileList={fileList}
                  beforeUpload={() => false}
                  onChange={({ fileList: fl }) => { setFileList(fl); setFolderFiles([]) }}
                >
                  <Button icon={<UploadOutlined />}>选择单个文件</Button>
                </Upload>
                <label>
                  <Button
                    icon={<UploadOutlined />}
                    onClick={() => document.getElementById('folder-input')?.click()}
                  >
                    选择文件夹
                  </Button>
                  <input
                    id="folder-input"
                    type="file"
                    style={{ display: 'none' }}
                    // @ts-ignore
                    webkitdirectory=""
                    multiple
                    onChange={handleFolderSelect}
                  />
                </label>
              </Space>
              {folderFiles.length > 0 && (
                <div style={{ fontSize: 12, color: '#1677ff' }}>
                  已选择文件夹，共 {folderFiles.length} 个 MD 文件：
                  {folderFiles.slice(0, 5).map(f => (
                    <div key={f.name} style={{ color: '#666', paddingLeft: 8 }}>· {f.webkitRelativePath || f.name}</div>
                  ))}
                  {folderFiles.length > 5 && <div style={{ color: '#999', paddingLeft: 8 }}>...还有 {folderFiles.length - 5} 个文件</div>}
                </div>
              )}
              <div style={{ fontSize: 12, color: '#999' }}>
                支持 EVB 知识库问答集格式（## chapter / doc_name + Q/A 结构）
              </div>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* 报告抽屉 */}
      <Drawer
        title={`测试报告 — ${tasks.find(t => t.id === reportDrawer)?.name || ''}`}
        open={!!reportDrawer}
        onClose={() => { setReportDrawer(null); setSelectedSection(null); setResults([]) }}
        width="85%"
        styles={{ body: { padding: '16px 24px' } }}
      >
        {!summary ? <Spin /> : (
          <>
            <SummaryCards summary={summary} />
            <div style={{ marginBottom: 12 }}>
              <Space>
                <Button
                  icon={<DownloadOutlined />}
                  onClick={handleExportFailed}
                  disabled={!summary?.empty_questions}
                >
                  导出召回失败问题 {summary?.empty_questions ? `(${summary.empty_questions} 条)` : ''}
                </Button>
                <Button
                  icon={<DownloadOutlined />}
                  onClick={handleExportFileMiss}
                  disabled={!summary?.file_miss_questions}
                >
                  导出文件命中失败问题 {summary?.file_miss_questions ? `(${summary.file_miss_questions} 条)` : ''}
                </Button>
              </Space>
            </div>

            <Divider orientation="left">章节统计</Divider>
            <div style={{ marginBottom: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
              <Text type="secondary">共 {sections.length} 个章节，点击「查看问题」可按章节筛选</Text>
              {selectedSection && (
                <Button size="small" onClick={() => handleSectionChange(null)}>清除筛选</Button>
              )}
            </div>
            <Table
              rowKey="section_path"
              dataSource={sections}
              columns={sectionColumns}
              size="small"
              pagination={{ pageSize: 10 }}
              rowClassName={(r) => r.section_path === selectedSection ? 'ant-table-row-selected' : ''}
            />

            <Divider orientation="left">
              {selectedSection ? `问题详情 — ${selectedSection}` : '问题详情（点击章节行查看）'}
            </Divider>
            {selectedSection ? (
              <Spin spinning={resultLoading}>
                <Table
                  rowKey="id"
                  dataSource={results}
                  columns={resultColumns}
                  size="small"
                  pagination={{ pageSize: 20 }}
                />
              </Spin>
            ) : (
              <Empty description="请在章节表格中点击「查看问题」" />
            )}
          </>
        )}
      </Drawer>

      {/* 问题详情抽屉 */}
      <Drawer
        title={`问题详情 — ${detailDrawer?.qid}`}
        open={!!detailDrawer}
        onClose={() => { setDetailDrawer(null); setAgentRecallItems([]) }}
        width={560}
      >
        {detailDrawer && (
          <div>
            <Paragraph><Text strong>问题：</Text>{detailDrawer.question}</Paragraph>
            <Paragraph><Text strong>参考答案：</Text>{detailDrawer.reference_answer}</Paragraph>
            <Paragraph>
              <Text strong>预期文件：</Text>
              {(detailDrawer.expected_file_name || detailDrawer.file_name)
                ? <Text code style={{ fontSize: 11 }}>{detailDrawer.expected_file_name || detailDrawer.file_name}</Text>
                : <Text type="secondary">未匹配</Text>
              }
              {detailDrawer.match_type && <Tag style={{ marginLeft: 8 }}>{detailDrawer.match_type}</Tag>}
            </Paragraph>
            {detailDrawer.file_id && (
              <Paragraph>
                <Text strong>预期文件ID：</Text>
                <Text code style={{ fontSize: 11 }}>{detailDrawer.file_id}</Text>
              </Paragraph>
            )}
            {/* 预期切片信息 */}
            {detailDrawer.expected_chunk_id && (
              <Paragraph>
                <Text strong>预期切片：</Text>
                <Text code style={{ fontSize: 11 }}>{detailDrawer.expected_chunk_name || detailDrawer.section_path || '未知'}</Text>
                <Tag color={detailDrawer.is_chunk_hit ? 'green' : 'orange'} style={{ marginLeft: 8 }}>
                  {detailDrawer.is_chunk_hit ? `命中 (Top${detailDrawer.chunk_hit_rank})` : '未命中'}
                </Tag>
              </Paragraph>
            )}
            {detailDrawer.error && (
              <Paragraph><Text type="danger">错误：{detailDrawer.error}</Text></Paragraph>
            )}
            <Divider>召回结果（{detailDrawer.retrieved?.length || 0} 条）</Divider>
            {(detailDrawer.retrieved || []).map((chunk: any, i: number) => (
              <Card key={i} size="small" style={{ marginBottom: 8 }}
                title={
                  <Space wrap>
                    <Text>#{i + 1}</Text>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      相似度: {chunk.cosine_distance_1 != null ? (1 - chunk.cosine_distance_1).toFixed(4) : '-'}
                    </Text>
                    {/* 切片命中标识 */}
                    {detailDrawer.expected_chunk_id && chunk.id === detailDrawer.expected_chunk_id ? (
                      <Tag color="green" icon={<CheckCircleOutlined />}>命中预期切片</Tag>
                    ) : detailDrawer.file_id && chunk.file_id === detailDrawer.file_id ? (
                      <Tag color="blue" icon={<CheckCircleOutlined />}>命中预期文件</Tag>
                    ) : (
                      <Tag color="orange">其他</Tag>
                    )}
                    {chunk.file_id && (
                      <Text type="secondary" style={{ fontSize: 10 }}>
                        文件: {chunk.display_file_name || chunk.file_name || '未知文件'}
                      </Text>
                    )}
                    {chunk.file_id && (
                      <Tooltip title={chunk.file_id}>
                        <Text type="secondary" style={{ fontSize: 10 }}>
                          ID: {chunk.file_id}
                        </Text>
                      </Tooltip>
                    )}
                  </Space>
                }
              >
                <Text style={{ fontSize: 12 }}>{chunk.active_paragraph_context?.slice(0, 300)}</Text>
                {chunk.headers && <div style={{ marginTop: 4, fontSize: 11, color: '#999' }}>标题: {chunk.headers}</div>}
              </Card>
            ))}

            <Divider>在线 Agent 召回结果对照</Divider>
            <Space direction="vertical" style={{ width: '100%' }} size={8}>
              <Text type="secondary">优先从下拉选择 Agent（也支持直接手填），拉取该问题在 Agent 链路中的真实召回结果。</Text>
              <Space.Compact style={{ width: '100%' }}>
                <Select
                  showSearch
                  allowClear
                  style={{ width: '100%' }}
                  placeholder="请选择 agent"
                  value={agentIdForRecall || undefined}
                  options={agentOptions}
                  loading={agentOptionsLoading}
                  onChange={(v) => setAgentIdForRecall(v || '')}
                  filterOption={(input, option) => ((option?.label as string) || '').toLowerCase().includes(input.toLowerCase())}
                />
                <Button loading={agentRecallLoading} onClick={loadAgentRecall}>
                  拉取在线召回
                </Button>
              </Space.Compact>
              <Input
                placeholder="如果下拉没有，手动输入 agent_id"
                value={agentIdForRecall}
                onChange={(e) => setAgentIdForRecall(e.target.value)}
              />
            </Space>
            <div style={{ marginTop: 12 }}>
              {agentRecallLoading ? (
                <Spin />
              ) : agentRecallItems.length ? (
                agentRecallItems.map((item: any, i: number) => (
                  <Card key={`${item.file_id || 'f'}-${i}`} size="small" style={{ marginBottom: 8 }}
                    title={
                      <Space wrap>
                        <Text>#{i + 1}</Text>
                        <Text code style={{ fontSize: 11 }}>{item.file_name || '未知文件名'}</Text>
                        {item.file_id && <Text type="secondary" style={{ fontSize: 10 }}>ID: {item.file_id}</Text>}
                        {item.similarity != null && <Tag color="blue">相似度 {item.similarity}</Tag>}
                      </Space>
                    }
                  >
                    <Text style={{ fontSize: 12 }}>{item.content?.slice(0, 300) || '-'}</Text>
                    {item.headers && <div style={{ marginTop: 4, fontSize: 11, color: '#999' }}>标题: {item.headers}</div>}
                  </Card>
                ))
              ) : (
                <Empty description="暂未拉取在线 Agent 召回结果" />
              )}
            </div>
          </div>
        )}
      </Drawer>
    </div>
  )
}
