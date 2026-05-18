import React, { useEffect, useRef, useState } from 'react'
import {
  Table, Button, Modal, Form, Input, InputNumber, Select, Upload,
  Tag, Progress, Drawer, Space, Tooltip, Typography, message, Popconfirm,
  Segmented, Empty, Pagination, Spin, Card, Row, Col, Statistic, Radio, Switch,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, ReloadOutlined, UploadOutlined,
  SyncOutlined, CheckCircleOutlined, CloseCircleOutlined,
  WarningOutlined, DownloadOutlined, CheckOutlined, CloseOutlined,
  EditOutlined, ThunderboltOutlined, DatabaseOutlined, AimOutlined, SearchOutlined,
} from '@ant-design/icons'
import { multiHopGenApi, multiHopApi, configApi, promptTemplateApi } from '../../services/api'
import DagentFileSelector from '../../components/DagentFileSelector'

const { Text } = Typography

function StatusTag({ status }: { status: string }) {
  const map: Record<string, { color: string; icon?: React.ReactNode; label: string }> = {
    pending: { color: 'default', label: '等待中' },
    running: { color: 'processing', icon: <SyncOutlined spin />, label: '生成中' },
    done:    { color: 'success',   label: '完成' },
    failed:  { color: 'error',     label: '失败' },
  }
  const cfg = map[status] || { color: 'default', label: status }
  return <Tag color={cfg.color} icon={cfg.icon}>{cfg.label}</Tag>
}

function QStatusTag({ status }: { status: string }) {
  const map: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
    pending:  { color: 'default', icon: <WarningOutlined />,     label: '待审核' },
    approved: { color: 'success', icon: <CheckCircleOutlined />, label: '已通过' },
    rejected: { color: 'error',   icon: <CloseCircleOutlined />, label: '已拒绝' },
  }
  const cfg = map[status] || { color: 'default', icon: null, label: status }
  return <Tag color={cfg.color} icon={cfg.icon}>{cfg.label}</Tag>
}

function TypeTag({ type }: { type: string }) {
  const map: Record<string, string> = {
    comparison:  '比较型',
    reasoning:   '推理型',
    aggregation: '聚合型',
  }
  return <Tag>{map[type] || type}</Tag>
}

function EditModal({ question, onOk, onCancel }: { question: any; onOk: (v: any) => void; onCancel: () => void }) {
  const [form] = Form.useForm()
  useEffect(() => {
    form.setFieldsValue({ question: question.question, answer: question.answer, type: question.type })
  }, [question])
  return (
    <Modal title="编辑多跳问题" open onOk={() => form.validateFields().then(onOk)} onCancel={onCancel} width={640}>
      <Form form={form} layout="vertical">
        <Form.Item name="type" label="类型">
          <Select options={[
            { label: '推理型', value: 'reasoning' },
            { label: '比较型', value: 'comparison' },
            { label: '聚合型', value: 'aggregation' },
          ]} />
        </Form.Item>
        <Form.Item name="question" label="问题" rules={[{ required: true }]}>
          <Input.TextArea rows={3} />
        </Form.Item>
        <Form.Item name="answer" label="参考答案" rules={[{ required: true }]}>
          <Input.TextArea rows={4} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

export default function GenTab() {
  const [tasks, setTasks] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [createModal, setCreateModal] = useState(false)
  const [form] = Form.useForm()
  const [fileList, setFileList] = useState<any[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [judgeOptions, setJudgeOptions] = useState<{ label: string; value: string }[]>([])
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Dagent 数据源
  const [dataSource, setDataSource] = useState<'file' | 'dagent'>('file')
  const [dagentStats, setDagentStats] = useState<any>(null)
  const [loadingStats, setLoadingStats] = useState(false)

  const [reviewDrawer, setReviewDrawer] = useState<string | null>(null)
  const [reviewTask, setReviewTask] = useState<any>(null)
  const [questions, setQuestions] = useState<any[]>([])
  const [questionTotal, setQuestionTotal] = useState(0)
  const [questionPage, setQuestionPage] = useState(1)
  const [questionLoading, setQuestionLoading] = useState(false)
  const [statusFilter, setStatusFilter] = useState('all')
  const [editingQ, setEditingQ] = useState<any>(null)
  const [detailQ, setDetailQ] = useState<any>(null)
  const PAGE_SIZE = 30

  // 提示词模板
  const [templates, setTemplates] = useState<any[]>([])
  const [templateDrawer, setTemplateDrawer] = useState(false)
  const [editingTemplate, setEditingTemplate] = useState<any>(null)  // null=新建, obj=编辑
  const [templateForm] = Form.useForm()
  const [templateSubmitting, setTemplateSubmitting] = useState(false)
  const [selectedTemplateContent, setSelectedTemplateContent] = useState<string | null>(null)

  const loadTasks = async () => {
    setLoading(true)
    try {
      const res = await multiHopGenApi.listTasks() as any
      setTasks(res.data || [])
    } finally {
      setLoading(false)
    }
  }

  const loadTemplates = async () => {
    try {
      const res = await promptTemplateApi.list() as any
      setTemplates(res.data || [])
    } catch { /* ignore */ }
  }

  const handleTemplateSave = async () => {
    const vals = await templateForm.validateFields()
    setTemplateSubmitting(true)
    try {
      if (editingTemplate?.id) {
        await promptTemplateApi.update(editingTemplate.id, vals)
        message.success('已更新')
      } else {
        await promptTemplateApi.create(vals)
        message.success('已创建')
      }
      templateForm.resetFields()
      setEditingTemplate(null)
      loadTemplates()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || e?.message || '保存失败')
    } finally {
      setTemplateSubmitting(false)
    }
  }

  const handleTemplateDelete = async (id: string) => {
    await promptTemplateApi.delete(id)
    message.success('已删除')
    loadTemplates()
  }

  const handleImportDefault = async () => {
    try {
      const res = await promptTemplateApi.getDefault() as any
      templateForm.setFieldValue('content', res.data?.content || '')
    } catch { /* ignore */ }
  }

  const loadJudgeOptions = async () => {
    try {
      const res = await configApi.listJudges() as any
      setJudgeOptions((res.data || []).map((j: any) => ({
        label: `${j.name} (${j.model})`,
        value: j.id,
      })))
    } catch { /* ignore */ }
  }

  useEffect(() => {
    loadTasks()
    loadJudgeOptions()
    loadTemplates()
    pollingRef.current = setInterval(() => {
      setTasks(prev => {
        const hasRunning = prev.some(t => t.status === 'running' || t.status === 'pending')
        if (hasRunning) loadTasks()
        return prev
      })
    }, 3000)
    return () => { if (pollingRef.current) clearInterval(pollingRef.current) }
  }, [])

  const loadDagentStats = async (orgId: string) => {
    if (!orgId || orgId.length < 8) return
    const envUrl = form.getFieldValue('env_url') || ''
    setLoadingStats(true)
    try {
      const res = await multiHopGenApi.getDagentStats(orgId, envUrl) as any
      setDagentStats(res.data || null)
    } catch (e: any) {
      message.error(`加载统计信息失败: ${e.message || '未知错误'}`)
      setDagentStats(null)
    } finally {
      setLoadingStats(false)
    }
  }

  const handleCreate = async () => {
    const vals = await form.validateFields()
    setSubmitting(true)
    try {
      const fd = new FormData()
      fd.append('prompt_template_id', vals.prompt_template_id || '')
      if (dataSource === 'file') {
        if (!fileList.length) { message.error('请上传知识库 MD 文件'); return }
        fd.append('file', fileList[0].originFileObj)
        fd.append('name', vals.name || fileList[0].name)
        fd.append('judge_config_id', vals.judge_config_id)
        fd.append('hops_per_question', String(vals.hops_per_question ?? 2))
        fd.append('questions_per_group', String(vals.questions_per_group ?? 3))
        fd.append('quality_threshold', String(vals.quality_threshold ?? 0.6))
        await multiHopGenApi.createTask(fd)
      } else {
        fd.append('org_id', vals.org_id)
        fd.append('env_url', vals.env_url || '')
        fd.append('name', vals.name || `Dagent多跳(${vals.org_id.slice(0, 8)}...)`)
        fd.append('judge_config_id', vals.judge_config_id)
        fd.append('file_ids', vals.file_ids || '')
        fd.append('hops_per_question', String(vals.hops_per_question ?? 2))
        fd.append('questions_per_group', String(vals.questions_per_group ?? 3))
        fd.append('quality_threshold', String(vals.quality_threshold ?? 0.6))
        await multiHopGenApi.createTaskFromDagent(fd)
      }
      message.success('生成任务已创建')
      setCreateModal(false)
      form.resetFields()
      setSelectedTemplateContent(null)
      setFileList([])
      setDagentStats(null)
      setDataSource('file')
      loadTasks()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || e?.message || '创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await multiHopGenApi.deleteTask(id)
      message.success('已删除')
      loadTasks()
      if (reviewDrawer === id) setReviewDrawer(null)
    } catch (e: any) {
      message.error(e?.message || '删除失败')
    }
  }

  const openReview = async (taskId: string) => {
    setReviewDrawer(taskId)
    setStatusFilter('all')
    setQuestions([])
    setQuestionPage(1)
    try {
      const res = await multiHopGenApi.getTask(taskId) as any
      setReviewTask(res.data)
    } catch {
      message.error('加载失败')
      setReviewDrawer(null)
    }
  }

  const loadQuestions = async (taskId: string, page = 1) => {
    setQuestionLoading(true)
    try {
      const res = await multiHopGenApi.listQuestions(taskId, {
        status: statusFilter === 'all' ? undefined : statusFilter,
        page,
        page_size: PAGE_SIZE,
      }) as any
      setQuestions(res.data?.items || [])
      setQuestionTotal(res.data?.total || 0)
      setQuestionPage(page)
    } finally {
      setQuestionLoading(false)
    }
  }

  useEffect(() => {
    if (reviewDrawer) loadQuestions(reviewDrawer, 1)
  }, [reviewDrawer, statusFilter])

  const refreshReview = async () => {
    if (!reviewDrawer) return
    const res = await multiHopGenApi.getTask(reviewDrawer) as any
    setReviewTask(res.data)
    loadQuestions(reviewDrawer, questionPage)
  }

  const handleApprove = async (id: string) => {
    await multiHopGenApi.approveQuestion(id)
    refreshReview()
  }

  const handleReject = async (id: string) => {
    await multiHopGenApi.rejectQuestion(id)
    refreshReview()
  }

  const handleEdit = async (vals: any) => {
    if (!editingQ) return
    await multiHopGenApi.editQuestion(editingQ.id, vals)
    setEditingQ(null)
    message.success('已保存并通过')
    refreshReview()
  }

  const handleBatchApprove = async (minQuality: number) => {
    if (!reviewDrawer) return
    await multiHopGenApi.batchApprove(reviewDrawer, minQuality)
    message.success('批量通过完成')
    refreshReview()
  }

  const handleExport = () => {
    if (!reviewDrawer) return
    const url = multiHopGenApi.exportMd(reviewDrawer)
    const link = document.createElement('a')
    link.href = url
    link.download = `multi_hop_${reviewDrawer.slice(0, 8)}.md`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  const [testModal, setTestModal] = useState(false)
  const [testForm] = Form.useForm()
  const [testSubmitting, setTestSubmitting] = useState(false)
  const [testAgentOptions, setTestAgentOptions] = useState<{ label: string; value: string }[]>([])
  const [testAgentLoading, setTestAgentLoading] = useState(false)

  const loadTestAgents = async () => {
    const envUrl = testForm.getFieldValue('env_url')
    const orgId = testForm.getFieldValue('org_id')
    const dUserId = testForm.getFieldValue('d_user_id') || 'test'
    if (!envUrl || !orgId) { message.warning('请先填写环境地址和 Org ID'); return }
    setTestAgentLoading(true)
    try {
      const res = await multiHopApi.listDagentAgents(envUrl, orgId, dUserId) as any
      const agents = res.data || []
      if (!agents.length) { message.warning('未找到可用的 Agent'); return }
      setTestAgentOptions(agents.map((a: any) => ({ label: `${a.name || a.id} (${String(a.id).slice(0, 8)}...)`, value: a.id })))
      message.success(`找到 ${agents.length} 个 Agent`)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || e?.message || '拉取 Agent 列表失败')
    } finally {
      setTestAgentLoading(false)
    }
  }

  const handleCreateTest = async () => {
    if (!reviewDrawer) return
    const vals = await testForm.validateFields()
    setTestSubmitting(true)
    try {
      const res = await multiHopGenApi.createTest(reviewDrawer, {
        env_url: vals.env_url,
        org_id: vals.org_id,
        agent_id: vals.agent_id,
        llm_type: vals.llm_type || 'deepseek_v3',
        d_user_id: vals.d_user_id || 'test',
        top_k: vals.top_k ?? 10,
        concurrency: vals.concurrency ?? 5,
        name: vals.name || '',
      }) as any
      message.success(`召回测试已创建，共 ${res.data.question_count} 题，请切换到「召回测试」Tab 查看进度`)
      setTestModal(false)
      testForm.resetFields()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || e?.message || '创建失败')
    } finally {
      setTestSubmitting(false)
    }
  }

  const columns = [
    { title: '任务名称', dataIndex: 'name', ellipsis: true },
    { title: '状态', dataIndex: 'status', width: 100, render: (v: string) => <StatusTag status={v} /> },
    {
      title: '进度', width: 160,
      render: (_: any, r: any) => r.status === 'running'
        ? <Progress percent={r.total ? Math.round(r.progress / r.total * 100) : 0} size="small" />
        : r.status === 'done'
          ? <Text type="success">{r.total} 组完成</Text>
          : r.status === 'failed'
            ? <Tooltip title={r.error_message}><Text type="danger">失败</Text></Tooltip>
            : '-',
    },
    {
      title: '已通过', width: 90,
      render: (_: any, r: any) => r.status === 'done'
        ? <Text type="success">{r.approved ?? 0} 题</Text>
        : '-',
    },
    { title: '创建时间', dataIndex: 'created_at', width: 160, render: (v: string) => v?.slice(0, 19) },
    {
      title: '操作', width: 160,
      render: (_: any, r: any) => (
        <Space>
          <Button size="small" disabled={r.status !== 'done'} onClick={() => openReview(r.id)}>审核</Button>
          <Button size="small" danger onClick={() => handleDelete(r.id)}>删除</Button>
        </Space>
      ),
    },
  ]

  const statusOptions = [
    { label: '全部', value: 'all' },
    { label: '待审核', value: 'pending' },
    { label: '已通过', value: 'approved' },
    { label: '已拒绝', value: 'rejected' },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={loadTasks}>刷新</Button>
          <Button icon={<EditOutlined />} onClick={() => { setTemplateDrawer(true); loadTemplates() }}>提示词模板</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModal(true)}>新建生成任务</Button>
        </Space>
      </div>

      <Table
        rowKey="id"
        dataSource={tasks}
        columns={columns}
        loading={loading}
        size="small"
        pagination={{ pageSize: 20 }}
      />

      {/* 新建弹窗 */}
      <Modal
        title="新建多跳 Case 生成任务"
        open={createModal}
        onOk={handleCreate}
        onCancel={() => {
          setCreateModal(false); form.resetFields(); setFileList([])
          setDagentStats(null); setDataSource('file'); setSelectedTemplateContent(null)
        }}
        confirmLoading={submitting}
        width={560}
      >
        <Form form={form} layout="vertical"
          initialValues={{ hops_per_question: 2, questions_per_group: 3, quality_threshold: 0.6 }}>

          {/* 数据来源切换 */}
          <Form.Item label="数据来源">
            <Radio.Group value={dataSource} onChange={e => { setDataSource(e.target.value); setDagentStats(null) }}>
              <Radio value="file"><UploadOutlined /> 上传 MD 文件</Radio>
              <Radio value="dagent"><DatabaseOutlined /> 从 Dagent 知识库导入</Radio>
            </Radio.Group>
          </Form.Item>

          <Form.Item name="name" label="任务名称">
            <Input placeholder={dataSource === 'file' ? '可选，默认使用文件名' : '可选，默认使用组织 ID'} />
          </Form.Item>
          <Form.Item name="judge_config_id" label="LLM 配置" rules={[{ required: true, message: '请选择 LLM 配置' }]}>
            <Select options={judgeOptions} placeholder="请选择用于生成的 LLM" />
          </Form.Item>
          <Form.Item
            name="prompt_template_id"
            label={
              <Space size={4}>
                <span>提示词模板</span>
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0, height: 'auto', fontSize: 12 }}
                  onClick={() => { setTemplateDrawer(true); loadTemplates() }}
                >
                  管理模板
                </Button>
              </Space>
            }
          >
            <Select
              placeholder="使用默认（不选则使用内置提示词）"
              allowClear
              options={[
                ...templates.map(t => ({ label: t.name, value: t.id })),
              ]}
              onChange={(val) => {
                const tpl = templates.find(t => t.id === val)
                setSelectedTemplateContent(tpl?.content || null)
              }}
              onClear={() => setSelectedTemplateContent(null)}
            />
          </Form.Item>
          {selectedTemplateContent && (
            <div style={{
              marginTop: -12, marginBottom: 12, padding: '8px 10px',
              background: '#f6f8fa', border: '1px solid #e8e8e8', borderRadius: 4,
              fontSize: 12, color: '#555', whiteSpace: 'pre-wrap', maxHeight: 120, overflowY: 'auto',
            }}>
              {selectedTemplateContent}
            </div>
          )}
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="hops_per_question" label="每题 Hop 数" tooltip="每个问题需要跨越的章节/文件数，建议 2-3">
                <InputNumber min={2} max={5} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="questions_per_group" label="每组问题数">
                <InputNumber min={1} max={10} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="quality_threshold" label="自动通过阈值">
                <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>

          {dataSource === 'file' ? (
            <Form.Item label="知识库 MD 文件" required>
              <Upload
                accept=".md"
                maxCount={1}
                fileList={fileList}
                beforeUpload={() => false}
                onChange={({ fileList: fl }) => setFileList(fl)}
              >
                <Button icon={<UploadOutlined />}>选择文件</Button>
              </Upload>
              <div style={{ marginTop: 4, color: '#888', fontSize: 12 }}>
                按 ## 标题切分章节，LLM 跨章节生成多跳问题
              </div>
            </Form.Item>
          ) : (
            <>
              <Form.Item name="env_url" label="Dagent 环境地址" rules={[{ required: true, message: '请输入环境地址' }]}>
                <Input placeholder="https://dagent.d-robotics.cc" />
              </Form.Item>

              <Form.Item name="org_id" label="Dagent 组织 ID" rules={[{ required: true, message: '请输入组织 ID' }]}>
                <Input.Search
                  placeholder="输入 org_id 后点击查询统计"
                  enterButton="查询"
                  loading={loadingStats}
                  onSearch={loadDagentStats}
                />
              </Form.Item>
              {dagentStats && (
                <div style={{ background: '#f6ffed', border: '1px solid #b7eb8f', borderRadius: 6, padding: '10px 14px', marginBottom: 16 }}>
                  <Row gutter={16}>
                    <Col span={8}><Statistic title="文件数" value={dagentStats.file_count ?? 0} valueStyle={{ fontSize: 18 }} /></Col>
                    <Col span={8}><Statistic title="段落数" value={dagentStats.paragraph_count ?? 0} valueStyle={{ fontSize: 18 }} /></Col>
                    <Col span={8}><Statistic title="含图段落" value={dagentStats.paragraphs_with_pic_text ?? 0} valueStyle={{ fontSize: 18 }} /></Col>
                  </Row>
                </div>
              )}
              <Form.Item name="file_ids" label="选择文件" tooltip="留空则使用全部已处理文件，每个文件取最具代表性的段落参与多跳组合">
                <DagentFileSelector
                  orgId={form.getFieldValue('org_id') || ''}
                  envUrl={form.getFieldValue('env_url') || ''}
                  disabled={!form.getFieldValue('org_id')}
                />
              </Form.Item>
            </>
          )}
        </Form>
      </Modal>

      {/* 审核 Drawer */}
      <Drawer
        title={`多跳 Case 审核 — ${reviewTask?.name || ''}`}
        open={!!reviewDrawer}
        onClose={() => { setReviewDrawer(null); setReviewTask(null) }}
        width="80%"
        extra={
          <Space>
            <Button icon={<DownloadOutlined />} onClick={handleExport} disabled={!reviewTask?.approved}>
              导出 {reviewTask?.approved ? `(${reviewTask.approved} 题)` : ''}
            </Button>
            <Button
              type="primary"
              icon={<AimOutlined />}
              disabled={!reviewTask?.approved}
              onClick={() => {
                testForm.setFieldsValue({ name: `${reviewTask?.name || ''}-召回测试` })
                setTestModal(true)
              }}
            >
              创建召回测试
            </Button>
          </Space>
        }
      >
        {!reviewTask ? <Spin /> : (
          <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            <Card size="small" style={{ marginBottom: 12 }}>
              <Row gutter={16}>
                <Col span={6}><Statistic title="总组数" value={reviewTask.total || 0} /></Col>
                <Col span={6}><Statistic title="已通过" value={reviewTask.approved || 0} valueStyle={{ color: '#52c41a' }} /></Col>
                <Col span={6}><Statistic title="进度" value={reviewTask.total ? Math.round(reviewTask.progress / reviewTask.total * 100) : 0} suffix="%" /></Col>
                <Col span={6}><StatusTag status={reviewTask.status} /></Col>
              </Row>
            </Card>

            <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Segmented
                options={statusOptions}
                value={statusFilter}
                onChange={v => { setStatusFilter(v as string); setQuestionPage(1) }}
              />
              <Space>
                <Button size="small" icon={<ThunderboltOutlined />} onClick={() => handleBatchApprove(0.6)}>
                  通过高质量(≥0.6)
                </Button>
                <Button size="small" onClick={() => handleBatchApprove(0)}>全部通过</Button>
              </Space>
            </div>

            <div style={{ flex: 1, overflow: 'auto' }}>
              <Spin spinning={questionLoading}>
                {questions.length === 0 && !questionLoading
                  ? <Empty description="暂无问题" />
                  : questions.map(q => (
                    <Card
                      key={q.id}
                      size="small"
                      style={{
                        marginBottom: 8,
                        borderColor: q.status === 'approved' ? '#b7eb8f'
                          : q.status === 'rejected' ? '#ffa39e' : undefined,
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ marginBottom: 4 }}>
                            <Space size={4}>
                              <TypeTag type={q.type} />
                              <Text strong>{q.qid}</Text>
                              {q.quality_score != null && (
                                <Text type="secondary" style={{ fontSize: 12 }}>
                                  质量 {q.quality_score.toFixed(2)}
                                </Text>
                              )}
                            </Space>
                          </div>
                          <div style={{ fontWeight: 500, marginBottom: 4 }}>Q: {q.question}</div>
                          <div style={{ color: '#555', fontSize: 13, marginBottom: 6 }}>
                            <Text type="secondary">A: </Text>{q.answer}
                          </div>
                          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 4 }}>
                            {(q.hops || []).map((h: any, i: number) => (
                              <Tag key={i} style={{ fontSize: 11 }}>
                                Hop{i + 1}: {h.section_path?.split('/').pop() || h.section_path}
                              </Tag>
                            ))}
                          </div>
                          <QStatusTag status={q.status} />
                        </div>
                        <Space direction="vertical" size={4} style={{ flexShrink: 0 }}>
                          {q.status !== 'approved' && (
                            <Button size="small" type="primary" icon={<CheckOutlined />}
                              onClick={() => handleApprove(q.id)}>通过</Button>
                          )}
                          {q.status !== 'rejected' && (
                            <Button size="small" danger icon={<CloseOutlined />}
                              onClick={() => handleReject(q.id)}>拒绝</Button>
                          )}
                          <Button size="small" icon={<EditOutlined />} onClick={() => setEditingQ(q)}>编辑</Button>
                          <Button size="small" onClick={() => setDetailQ(q)}>详情</Button>
                        </Space>
                      </div>
                    </Card>
                  ))
                }
              </Spin>
            </div>

            {questionTotal > PAGE_SIZE && (
              <div style={{ marginTop: 12, textAlign: 'right' }}>
                <Pagination
                  size="small"
                  current={questionPage}
                  pageSize={PAGE_SIZE}
                  total={questionTotal}
                  onChange={p => { setQuestionPage(p); loadQuestions(reviewDrawer!, p) }}
                  showTotal={t => `共 ${t} 条`}
                />
              </div>
            )}
          </div>
        )}
      </Drawer>

      {/* 问题详情 Drawer */}
      <Drawer
        title={`${detailQ?.qid} 详情`}
        width={520}
        open={!!detailQ}
        onClose={() => setDetailQ(null)}
      >
        {detailQ && (
          <div>
            <Card size="small" title="问题" style={{ marginBottom: 12 }}>
              <Space style={{ marginBottom: 8 }}><TypeTag type={detailQ.type} /></Space>
              <div style={{ fontWeight: 500, marginBottom: 8 }}>{detailQ.question}</div>
              <Text type="secondary">参考答案：{detailQ.answer}</Text>
            </Card>
            <Card size="small" title="Hop 来源章节">
              {(detailQ.hops || []).map((h: any, i: number) => (
                <div key={i} style={{ marginBottom: 8, padding: '6px 8px', background: '#fafafa', borderRadius: 4, border: '1px solid #f0f0f0' }}>
                  <Text strong>Hop{i + 1}：</Text>
                  <Text code style={{ fontSize: 12 }}>{h.section_path}</Text>
                  {h.contribution && (
                    <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>{h.contribution}</div>
                  )}
                </div>
              ))}
            </Card>
          </div>
        )}
      </Drawer>

      {editingQ && (
        <EditModal question={editingQ} onOk={handleEdit} onCancel={() => setEditingQ(null)} />
      )}

      {/* 创建召回测试弹窗 */}
      <Modal
        title="创建召回测试"
        open={testModal}
        onOk={handleCreateTest}
        onCancel={() => { setTestModal(false); testForm.resetFields(); setTestAgentOptions([]) }}
        confirmLoading={testSubmitting}
        width={480}
      >
        <div style={{ marginBottom: 12, color: '#666', fontSize: 13 }}>
          将已通过的 <strong>{reviewTask?.approved ?? 0}</strong> 个多跳问题直接创建为召回测试任务
        </div>
        <Form form={testForm} layout="vertical" initialValues={{ d_user_id: 'test', top_k: 10, concurrency: 5, llm_type: 'deepseek_v3' }}>
          <Form.Item name="name" label="测试任务名称">
            <Input placeholder="可选" />
          </Form.Item>
          <Form.Item name="env_url" label="Agent 环境地址" rules={[{ required: true }]}>
            <Input placeholder="https://dagent.d-robotics.cc/dagent" />
          </Form.Item>
          <Form.Item name="org_id" label="Org ID" rules={[{ required: true }]}>
            <Input placeholder="a4d49699ba313815..." />
          </Form.Item>
          <Form.Item name="agent_id" label="Agent" rules={[{ required: true, message: '请选择 Agent' }]}>
            <Select
              placeholder="填写环境地址和 Org ID 后点右侧按钮查询"
              options={testAgentOptions}
              notFoundContent={testAgentOptions.length === 0 ? '点击下方「查询 Agent」' : '无匹配'}
              dropdownRender={menu => (
                <div>
                  {menu}
                  <div style={{ padding: '6px 8px', borderTop: '1px solid #f0f0f0' }}>
                    <Button
                      size="small"
                      icon={<SearchOutlined />}
                      loading={testAgentLoading}
                      onClick={loadTestAgents}
                      block
                    >
                      查询 Agent 列表
                    </Button>
                  </div>
                </div>
              )}
            />
          </Form.Item>
          <Form.Item name="llm_type" label="LLM 类型" tooltip="Agent 使用的 LLM，不同模型可用性取决于远程环境">
            <Select options={[
              { label: 'DeepSeek V3', value: 'deepseek_v3' },
              { label: 'DeepSeek R1', value: 'deepseek-r1' },
              { label: 'Volc DeepSeek V3', value: 'volc_deepseek_v3_250324' },
              { label: 'Azure GPT-4o', value: 'azure_openai_4o' },
              { label: 'Azure GPT-4.1', value: 'azure/gpt-4.1' },
              { label: 'Claude 3.5 Sonnet', value: 'aws/claude-3-5-sonnet' },
            ]} />
          </Form.Item>
          <Form.Item name="d_user_id" label="User ID">
            <Input />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="concurrency" label="并发数">
                <InputNumber min={1} max={10} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      {/* 提示词模板管理 Drawer */}
      <Drawer
        title="提示词模板管理"
        width={720}
        open={templateDrawer}
        onClose={() => { setTemplateDrawer(false); setEditingTemplate(null); templateForm.resetFields() }}
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingTemplate({}); templateForm.resetFields() }}>
            新建模板
          </Button>
        }
      >
        <Row gutter={16} style={{ height: '100%' }}>
          {/* 左侧：模板列表 */}
          <Col span={editingTemplate !== null ? 10 : 24}>
            {templates.length === 0 ? (
              <Empty description="暂无模板，点击右上角新建" />
            ) : (
              templates.map(t => (
                <Card
                  key={t.id}
                  size="small"
                  style={{ marginBottom: 8, cursor: 'pointer', border: editingTemplate?.id === t.id ? '1px solid #1677ff' : undefined }}
                  onClick={() => { setEditingTemplate(t); templateForm.setFieldsValue({ name: t.name, description: t.description, content: t.content }) }}
                  actions={[
                    <Button
                      key="edit"
                      type="link"
                      size="small"
                      icon={<EditOutlined />}
                      onClick={e => { e.stopPropagation(); setEditingTemplate(t); templateForm.setFieldsValue({ name: t.name, description: t.description, content: t.content }) }}
                    >
                      编辑
                    </Button>,
                    <Popconfirm
                      key="del"
                      title="确认删除此模板？"
                      onConfirm={e => { e?.stopPropagation(); handleTemplateDelete(t.id) }}
                    >
                      <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={e => e.stopPropagation()}>删除</Button>
                    </Popconfirm>,
                  ]}
                >
                  <div style={{ fontWeight: 500 }}>{t.name}</div>
                  {t.description && <Text type="secondary" style={{ fontSize: 12 }}>{t.description}</Text>}
                  <div style={{ marginTop: 6, fontSize: 12, color: '#888', whiteSpace: 'pre-wrap', maxHeight: 60, overflow: 'hidden' }}>
                    {t.content}
                  </div>
                </Card>
              ))
            )}
          </Col>

          {/* 右侧：编辑区 */}
          {editingTemplate !== null && (
            <Col span={14}>
              <Card
                size="small"
                title={editingTemplate.id ? '编辑模板' : '新建模板'}
                extra={
                  <Button size="small" onClick={() => { setEditingTemplate(null); templateForm.resetFields() }}>取消</Button>
                }
              >
                <Form form={templateForm} layout="vertical">
                  <Form.Item name="name" label="模板名称" rules={[{ required: true, message: '请输入名称' }]}>
                    <Input placeholder="例如：偏操作步骤型" />
                  </Form.Item>
                  <Form.Item name="description" label="描述（可选）">
                    <Input placeholder="简要说明此模板的用途" />
                  </Form.Item>
                  <Form.Item
                    name="content"
                    label={
                      <Space size={4}>
                        <span>生成要求</span>
                        <Button
                          type="link"
                          size="small"
                          style={{ padding: 0, height: 'auto', fontSize: 12 }}
                          onClick={handleImportDefault}
                        >
                          导入默认模板
                        </Button>
                      </Space>
                    }
                    rules={[{ required: true, message: '请输入生成要求' }]}
                    tooltip="只需填写生成要求，系统会自动拼接角色定义、章节内容和输出格式"
                  >
                    <Input.TextArea
                      rows={10}
                      placeholder={'1. 每个问题必须真正跨越多个章节...\n2. 问题类型可以是...\n3. ...'}
                    />
                  </Form.Item>
                  <Button type="primary" loading={templateSubmitting} onClick={handleTemplateSave} block>
                    保存
                  </Button>
                </Form>
              </Card>
            </Col>
          )}
        </Row>
      </Drawer>
    </div>
  )
}
