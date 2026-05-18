import React, { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Table, Button, Modal, Form, Input, InputNumber, Select, Upload,
  message, Popconfirm, Tag, Space, Progress, Drawer, Divider,
  Typography, Spin, Card, Row, Col, Statistic, Tooltip, Badge,
  Segmented, Empty, Pagination, Radio, Switch, Checkbox,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, EyeOutlined, ReloadOutlined,
  UploadOutlined, CheckOutlined, CloseOutlined, EditOutlined,
  DownloadOutlined, CheckCircleOutlined, CloseCircleOutlined,
  WarningOutlined, ThunderboltOutlined, DatabaseOutlined,
  RocketOutlined, LinkOutlined, PlayCircleOutlined, AimOutlined,
  SyncOutlined, PauseCircleOutlined, StopOutlined, BulbOutlined,
} from '@ant-design/icons'
import { qaGenApi, configApi, taskApi, singleJumpApi, loopApi, multiHopApi } from '../../services/api'
import DagentFileSelector from '../../components/DagentFileSelector'
import DagentTreeSelector from '../../components/DagentTreeSelector'
import { metricCn } from '../../constants/metrics'

const { Text, Paragraph } = Typography

// ── 状态标签 ──────────────────────────────────────────────────────────────────
function StatusTag({ status }: { status: string }) {
  const map: Record<string, { color: string; label: string }> = {
    pending:  { color: 'default',    label: '等待中' },
    running:  { color: 'processing', label: '生成中' },
    done:     { color: 'success',    label: '完成' },
    failed:   { color: 'error',      label: '失败' },
  }
  const cfg = map[status] || { color: 'default', label: status }
  return <Tag color={cfg.color}>{cfg.label}</Tag>
}

function QStatusTag({ status }: { status: string }) {
  const map: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
    pending:  { color: 'default',  icon: <WarningOutlined />,      label: '待审核' },
    approved: { color: 'success',  icon: <CheckCircleOutlined />,  label: '已通过' },
    rejected: { color: 'error',    icon: <CloseCircleOutlined />,  label: '已拒绝' },
  }
  const cfg = map[status] || { color: 'default', icon: null, label: status }
  return <Tag color={cfg.color} icon={cfg.icon}>{cfg.label}</Tag>
}

function LoopStatusTag({ status }: { status: string }) {
  const map: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
    pending:   { color: 'default',    icon: <WarningOutlined />,      label: '等待中' },
    running:   { color: 'processing', icon: <SyncOutlined spin />,    label: '运行中' },
    paused:    { color: 'orange',     icon: <PauseCircleOutlined />,  label: '已暂停' },
    stopped:   { color: 'default',    icon: <StopOutlined />,         label: '已停止' },
    done:      { color: 'success',    icon: <CheckCircleOutlined />,  label: '已完成' },
    failed:    { color: 'error',      icon: <CloseCircleOutlined />,  label: '失败' },
  }
  const cfg = map[status] || { color: 'default', icon: null, label: status }
  return <Tag color={cfg.color} icon={cfg.icon}>{cfg.label}</Tag>
}

function QualityBadge({ score }: { score: number | null }) {
  if (score == null) return <Text type="secondary">-</Text>
  const color = score >= 0.8 ? '#52c41a' : score >= 0.6 ? '#faad14' : '#ff4d4f'
  return <span style={{ color, fontWeight: 600 }}>{score.toFixed(2)}</span>
}

// ── 编辑问题弹窗 ──────────────────────────────────────────────────────────────
function EditModal({
  question, onOk, onCancel,
}: {
  question: any
  onOk: (vals: any) => void
  onCancel: () => void
}) {
  const [form] = Form.useForm()
  useEffect(() => {
    form.setFieldsValue({
      question: question.question,
      reference_answer: question.reference_answer,
    })
  }, [question])
  return (
    <Modal title="编辑问题" open onOk={() => form.validateFields().then(onOk)} onCancel={onCancel} width={600}>
      <Form form={form} layout="vertical">
        <Form.Item name="question" label="问题" rules={[{ required: true }]}>
          <Input.TextArea rows={3} />
        </Form.Item>
        <Form.Item name="reference_answer" label="参考答案" rules={[{ required: true }]}>
          <Input.TextArea rows={4} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

// ── 问题卡片 ──────────────────────────────────────────────────────────────────
function QuestionCard({
  q, onApprove, onReject, onEdit,
}: {
  q: any
  onApprove: () => void
  onReject: () => void
  onEdit: () => void
}) {
  const isDup = !!q.dup_of
  const isLowQuality = q.quality_score != null && q.quality_score < 0.6

  return (
    <Card
      size="small"
      style={{
        marginBottom: 8,
        borderColor: q.status === 'approved' ? '#b7eb8f'
          : q.status === 'rejected' ? '#ffa39e'
          : isDup || isLowQuality ? '#ffe58f' : undefined,
      }}
      bodyStyle={{ padding: '10px 14px' }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* 问题 */}
          <div style={{ fontWeight: 500, marginBottom: 4 }}>
            <Text>Q: {q.question}</Text>
          </div>
          {/* 答案 */}
          <div style={{ color: '#555', fontSize: 13, marginBottom: 6 }}>
            <Text type="secondary">A: </Text>{q.reference_answer}
          </div>
          {/* 切片信息 */}
          {(q.chunk_headers || q.file_name) && (
            <div style={{ fontSize: 12, color: '#666', marginBottom: 4 }}>
              {q.chunk_headers && (
                <Tag style={{ marginRight: 8, fontSize: 11 }}>切片: {q.chunk_headers}</Tag>
              )}
              {q.file_name && (
                <Tag color="blue" style={{ fontSize: 11 }}>文件: {q.file_name}</Tag>
              )}
            </div>
          )}
          {/* 来源 */}
          {q.source_chunk && (
            <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>
              <Text type="secondary">来源: {q.source_chunk.slice(0, 80)}{q.source_chunk.length > 80 ? '…' : ''}</Text>
            </div>
          )}
          {/* 警告标签 */}
          <Space size={4} wrap>
            <QStatusTag status={q.status} />
            <span style={{ fontSize: 12, color: '#888' }}>
              质量分: <QualityBadge score={q.quality_score} />
            </span>
            {isDup && (
              <Tag color="orange" icon={<WarningOutlined />}>
                疑似重复 (相似度 {q.dup_similarity?.toFixed(2)})
              </Tag>
            )}
            {isLowQuality && !isDup && (
              <Tag color="red" icon={<WarningOutlined />}>低质量</Tag>
            )}
          </Space>
        </div>
        {/* 操作按钮 */}
        <Space direction="vertical" size={4} style={{ flexShrink: 0 }}>
          {q.status !== 'approved' && (
            <Button size="small" type="primary" icon={<CheckOutlined />} onClick={onApprove}>通过</Button>
          )}
          {q.status !== 'rejected' && (
            <Button size="small" danger icon={<CloseOutlined />} onClick={onReject}>拒绝</Button>
          )}
          <Button size="small" icon={<EditOutlined />} onClick={onEdit}>编辑</Button>
        </Space>
      </div>
    </Card>
  )
}

// ── 主页面 ────────────────────────────────────────────────────────────────────
export default function QaGen() {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState<'generate' | 'loop'>('generate')

  // ── QA生成相关状态 ──────────────────────────────────────────────────────────────
  const [tasks, setTasks] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [createModal, setCreateModal] = useState(false)
  const [form] = Form.useForm()
  const [fileList, setFileList] = useState<any[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [judgeOptions, setJudgeOptions] = useState<{ label: string; value: string }[]>([])
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Dagent 数据源相关
  const [dataSource, setDataSource] = useState<'file' | 'dagent'>('file')
  const [dagentStats, setDagentStats] = useState<any>(null)
  const [loadingStats, setLoadingStats] = useState(false)
  const [fileSelectorMode, setFileSelectorMode] = useState<'list' | 'tree'>('tree')

  // 审核抽屉
  const [reviewDrawer, setReviewDrawer] = useState<string | null>(null)
  const [reviewTask, setReviewTask] = useState<any>(null)
  const [sections, setSections] = useState<any[]>([])
  const [selectedSection, setSelectedSection] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [questions, setQuestions] = useState<any[]>([])
  const [questionTotal, setQuestionTotal] = useState(0)
  const [questionPage, setQuestionPage] = useState(1)
  const [questionLoading, setQuestionLoading] = useState(false)
  const PAGE_SIZE = 30

  // 编辑弹窗
  const [editingQ, setEditingQ] = useState<any>(null)

  // ── 循环测试相关状态 ────────────────────────────────────────────────────────────
  const [loopTasks, setLoopTasks] = useState<any[]>([])
  const [loopLoading, setLoopLoading] = useState(false)
  const [loopCreateModal, setLoopCreateModal] = useState(false)
  const [loopForm] = Form.useForm()
  const loopOrgId = Form.useWatch('org_id', loopForm)
  const loopEnvUrl = Form.useWatch('env_url', loopForm)
  const [loopSubmitting, setLoopSubmitting] = useState(false)
  const [loopDetailDrawer, setLoopDetailDrawer] = useState<string | null>(null)
  const loopDetailDrawerRef = useRef<string | null>(null)
  useEffect(() => {
    loopDetailDrawerRef.current = loopDetailDrawer
  }, [loopDetailDrawer])
  const [loopDetail, setLoopDetail] = useState<any>(null)
  const [loopRounds, setLoopRounds] = useState<any[]>([])
  const [loopDetailLoading, setLoopDetailLoading] = useState(false)
  const loopPollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [exportModal, setExportModal] = useState(false)
  const [exportCategory, setExportCategory] = useState('all')
  const [createTaskModal, setCreateTaskModal] = useState(false)
  const [selectedTaskType, setSelectedTaskType] = useState<'eval' | 'single-jump' | null>(null)

  // 批量删除选中项
  const [selectedTaskKeys, setSelectedTaskKeys] = useState<React.Key[]>([])
  const [selectedLoopTaskKeys, setSelectedLoopTaskKeys] = useState<React.Key[]>([])

  // 自动创建评测任务弹窗
  const [evalTaskModal, setEvalTaskModal] = useState(false)
  const [evalTaskForm] = Form.useForm()
  const [platformOptions, setPlatformOptions] = useState<{ label: string; value: string }[]>([])
  const [evalSubmitting, setEvalSubmitting] = useState(false)

  // 自动创建单跳召回测试弹窗
  const [singleJumpTaskModal, setSingleJumpTaskModal] = useState(false)
  const [singleJumpForm] = Form.useForm()
  const singleJumpOrgId = Form.useWatch('org_id', singleJumpForm)
  const singleJumpEnvUrl = Form.useWatch('env_url', singleJumpForm)
  const [singleJumpSubmitting, setSingleJumpSubmitting] = useState(false)
  const [singleJumpAgentOptions, setSingleJumpAgentOptions] = useState<{ label: string; value: string }[]>([])
  const [singleJumpAgentOptionsLoading, setSingleJumpAgentOptionsLoading] = useState(false)

  // 循环测试任务创建时的 agent 选项
  const [loopAgentOptions, setLoopAgentOptions] = useState<{ label: string; value: string }[]>([])
  const [loopAgentOptionsLoading, setLoopAgentOptionsLoading] = useState(false)

  const loadTasks = async () => {
    setLoading(true)
    try {
      const res = await qaGenApi.listTasks() as any
      setTasks(res.data || [])
    } finally {
      setLoading(false)
    }
  }

  // ── 循环测试相关函数 ────────────────────────────────────────────────────────────
  const loadLoopTasks = async () => {
    setLoopLoading(true)
    try {
      const res = await loopApi.listTasks() as any
      setLoopTasks(res.data?.items || [])
    } finally {
      setLoopLoading(false)
    }
  }

  const loadLoopDetail = async (taskId: string) => {
    setLoopDetailLoading(true)
    try {
      const [taskRes, roundsRes] = await Promise.all([
        loopApi.getTask(taskId) as any,
        loopApi.getRounds(taskId) as any,
      ])
      setLoopDetail(taskRes.data)
      setLoopRounds(roundsRes.data || [])
    } finally {
      setLoopDetailLoading(false)
    }
  }

  const handleCreateLoopTask = async () => {
    const vals = await loopForm.validateFields()
    setLoopSubmitting(true)
    try {
      const fd = new FormData()
      fd.append('name', vals.name || `循环测试-${vals.org_id.slice(0, 8)}`)
      fd.append('org_id', vals.org_id)
      fd.append('judge_config_id', vals.judge_config_id)
      fd.append('file_ids', vals.file_ids || '')
      fd.append('questions_per_section', String(vals.questions_per_section ?? 5))
      fd.append('quality_threshold', String(vals.quality_threshold ?? 0.6))
      fd.append('include_multimodal', String(vals.include_multimodal ?? true))
      fd.append('env_url', vals.env_url)
      fd.append('d_user_id', vals.d_user_id || 'test')
      fd.append('agent_id', vals.agent_id || '')
      fd.append('top_k', String(vals.top_k ?? 64))
      fd.append('recall_top_k', String(vals.recall_top_k ?? 64))
      fd.append('concurrency', String(vals.concurrency ?? 20))
      fd.append('cross_chunk', String(vals.cross_chunk ?? true))
      fd.append('max_rounds', String(vals.max_rounds ?? 0))
      fd.append('max_questions', String(vals.max_questions ?? 0))

      await loopApi.createTask(fd)
      message.success('循环任务已创建')
      setLoopCreateModal(false)
      loopForm.resetFields()
      loadLoopTasks()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || e?.message || '创建失败')
    } finally {
      setLoopSubmitting(false)
    }
  }

  const handlePauseLoop = async (id: string) => {
    try {
      await loopApi.pauseTask(id)
      message.success('任务已暂停')
      loadLoopTasks()
      if (loopDetailDrawer === id) loadLoopDetail(id)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '暂停失败')
    }
  }

  const handleResumeLoop = async (id: string) => {
    try {
      await loopApi.resumeTask(id)
      message.success('任务已继续')
      loadLoopTasks()
      if (loopDetailDrawer === id) loadLoopDetail(id)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '继续失败')
    }
  }

  const handleStopLoop = async (id: string) => {
    try {
      await loopApi.stopTask(id)
      message.success('任务已停止')
      loadLoopTasks()
      if (loopDetailDrawer === id) loadLoopDetail(id)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '停止失败')
    }
  }

  const handleDeleteLoop = async (id: string) => {
    try {
      await loopApi.deleteTask(id)
      message.success('任务已删除')
      loadLoopTasks()
      if (loopDetailDrawer === id) setLoopDetailDrawer(null)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '删除失败')
    }
  }

  // ── 批量删除 ──────────────────────────────────────────────────────────────────
  const handleBatchDeleteTasks = async () => {
    if (selectedTaskKeys.length === 0) {
      message.warning('请先选择要删除的任务')
      return
    }
    Modal.confirm({
      title: `确认删除选中的 ${selectedTaskKeys.length} 个生成任务？`,
      content: '删除后将无法恢复，相关问题也会被删除。',
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      async onOk() {
        try {
          await Promise.all(selectedTaskKeys.map(id => qaGenApi.deleteTask(id as string)))
          message.success(`成功删除 ${selectedTaskKeys.length} 个任务`)
          setSelectedTaskKeys([])
          loadTasks()
        } catch (e: any) {
          message.error(e?.message || '批量删除失败')
        }
      },
    })
  }

  const handleBatchDeleteLoopTasks = async () => {
    if (selectedLoopTaskKeys.length === 0) {
      message.warning('请先选择要删除的循环任务')
      return
    }
    Modal.confirm({
      title: `确认删除选中的 ${selectedLoopTaskKeys.length} 个循环任务？`,
      content: '删除后将无法恢复，相关轮次和问题也会被删除。',
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      async onOk() {
        try {
          await Promise.all(selectedLoopTaskKeys.map(id => loopApi.deleteTask(id as string)))
          message.success(`成功删除 ${selectedLoopTaskKeys.length} 个循环任务`)
          setSelectedLoopTaskKeys([])
          loadLoopTasks()
          if (loopDetailDrawer && selectedLoopTaskKeys.includes(loopDetailDrawer)) {
            setLoopDetailDrawer(null)
          }
        } catch (e: any) {
          message.error(e?.message || '批量删除失败')
        }
      },
    })
  }

  const openLoopDetail = (id: string) => {
    setLoopDetailDrawer(id)
    loadLoopDetail(id)
  }

  const handleExport = (category: string) => {
    if (!loopDetailDrawer) return
    const url = loopApi.export(loopDetailDrawer, category, 'md')
    // Use anchor tag for more reliable download
    const link = document.createElement('a')
    link.href = url
    link.download = `loop_${loopDetailDrawer.slice(0, 8)}_${category}.md`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  const handleExportJson = (category: string) => {
    if (!loopDetailDrawer) return
    const url = loopApi.export(loopDetailDrawer, category, 'json')
    // Use anchor tag for more reliable download
    const link = document.createElement('a')
    link.href = url
    link.download = `loop_${loopDetailDrawer.slice(0, 8)}_${category}.json`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
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

  const loadPlatformOptions = async () => {
    try {
      const res = await configApi.listPlatforms() as any
      setPlatformOptions((res.data || []).map((p: any) => ({
        label: `${p.name} (${p.base_url})`,
        value: p.id,
      })))
    } catch { /* ignore */ }
  }

  // 当自动创建评测任务弹窗打开时，初始化表单值
  useEffect(() => {
    if (evalTaskModal && reviewTask) {
      evalTaskForm.setFieldsValue({
        name: `从QA生成任务导入-${reviewTask?.name || reviewDrawer?.slice(0, 8) || ''}`,
        judge_config_id: reviewTask.judge_config_id,
      })
    }
  }, [evalTaskModal, reviewTask, evalTaskForm, reviewDrawer])

  // 当自动创建单跳召回测试弹窗打开时，初始化表单值
  useEffect(() => {
    if (singleJumpTaskModal && reviewTask) {
      singleJumpForm.setFieldsValue({
        name: `从QA生成任务导入-${reviewTask?.name || reviewDrawer?.slice(0, 8) || ''}`,
      })
    }
  }, [singleJumpTaskModal, reviewTask, singleJumpForm, reviewDrawer])

  useEffect(() => {
    loadTasks()
    loadJudgeOptions()
    loadPlatformOptions()
    loadLoopTasks()  // 同时加载循环任务
    pollingRef.current = setInterval(() => {
      setTasks(prev => {
        const hasRunning = prev.some(t => t.status === 'running' || t.status === 'pending')
        if (hasRunning) loadTasks()
        return prev
      })
    }, 3000)
    // 循环任务轮询 - 使用独立函数避免闭包 stale state 问题
    loopPollingRef.current = setInterval(() => {
      // 直接查询 API 获取最新状态，不依赖闭包
      loadLoopTasks().then(() => {
        // 如果 Drawer 打开，同步刷新轮次详情
        const drawerId = loopDetailDrawerRef.current
        if (drawerId) {
          loadLoopDetail(drawerId)
        }
      })
    }, 3000)
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
      if (loopPollingRef.current) clearInterval(loopPollingRef.current)
    }
  }, [])

  // 当数据源切换时重置相关字段
  useEffect(() => {
    if (createModal) {
      if (dataSource === 'file') {
        form.setFieldsValue({ file_ids: '' })
        setDagentStats(null)
      } else {
        // 切换到Dagent模式时也重置file_ids
        form.setFieldsValue({ file_ids: '' })
      }
    }
  }, [dataSource, createModal])

  // 当org_id变化时重置文件选择
  useEffect(() => {
    if (createModal && dataSource === 'dagent') {
      const orgId = form.getFieldValue('org_id')
      if (orgId) {
        // org_id变化时重置选中的文件
        form.setFieldsValue({ file_ids: '' })
      }
    }
  }, [form.getFieldValue('org_id'), createModal, dataSource])

  // 当循环任务的 org_id 或 env_url 变化时，加载 agent 列表
  useEffect(() => {
    if (loopCreateModal && loopOrgId && loopEnvUrl) {
      loadLoopAgentOptions()
    }
  }, [loopOrgId, loopEnvUrl, loopCreateModal])

  // 加载循环测试任务创建时的 agent 选项
  const loadLoopAgentOptions = async () => {
    if (!loopOrgId || !loopEnvUrl) return
    setLoopAgentOptionsLoading(true)
    try {
      const res = await multiHopApi.listDagentAgents(loopEnvUrl, loopOrgId) as any
      const opts = (res?.data || []).map((a: any) => ({ label: `${a.name} (${a.id.slice(0, 8)}...)`, value: a.id }))
      setLoopAgentOptions(opts)
    } catch {
      setLoopAgentOptions([])
    } finally {
      setLoopAgentOptionsLoading(false)
    }
  }

  // 加载单跳召回测试创建时的 agent 选项
  const loadSingleJumpAgentOptions = async () => {
    if (!singleJumpOrgId || !singleJumpEnvUrl) return
    setSingleJumpAgentOptionsLoading(true)
    try {
      const res = await multiHopApi.listDagentAgents(singleJumpEnvUrl, singleJumpOrgId) as any
      const opts = (res?.data || []).map((a: any) => ({ label: `${a.name} (${a.id.slice(0, 8)}...)`, value: a.id }))
      setSingleJumpAgentOptions(opts)
    } catch {
      setSingleJumpAgentOptions([])
    } finally {
      setSingleJumpAgentOptionsLoading(false)
    }
  }

  // 当单跳召回测试的 org_id 或 env_url 变化时，加载 agent 列表
  useEffect(() => {
    if (singleJumpTaskModal && singleJumpOrgId && singleJumpEnvUrl) {
      loadSingleJumpAgentOptions()
    }
  }, [singleJumpOrgId, singleJumpEnvUrl, singleJumpTaskModal])

  const handleCreate = async () => {
    const vals = await form.validateFields()

    if (dataSource === 'file') {
      if (!fileList.length) { message.error('请上传知识库 MD 文件'); return }
    } else {
      if (!vals.org_id) { message.error('请输入 Dagent 组织 ID'); return }
    }

    setSubmitting(true)
    try {
      const fd = new FormData()

      if (dataSource === 'file') {
        fd.append('file', fileList[0].originFileObj)
        fd.append('name', vals.name || fileList[0].name)
        fd.append('judge_config_id', vals.judge_config_id)
        fd.append('questions_per_section', String(vals.questions_per_section ?? 5))
        fd.append('quality_threshold', String(vals.quality_threshold ?? 0.6))
        await qaGenApi.createTask(fd)
      } else {
        fd.append('org_id', vals.org_id)
        fd.append('env_url', vals.env_url || '')
        fd.append('name', vals.name || `Dagent导入(${vals.org_id.slice(0, 8)}...)`)
        fd.append('judge_config_id', vals.judge_config_id)
        fd.append('file_ids', vals.file_ids || '')
        fd.append('questions_per_section', String(vals.questions_per_section ?? 5))
        fd.append('quality_threshold', String(vals.quality_threshold ?? 0.6))
        fd.append('include_multimodal', String(vals.include_multimodal ?? true))
        await qaGenApi.createTaskFromDagent(fd)
      }

      message.success('生成任务已创建')
      setCreateModal(false)
      form.resetFields()
      setFileList([])
      setDagentStats(null)
      loadTasks()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || e?.message || '创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  const loadDagentStats = async (orgId: string, sourceForm?: ReturnType<typeof Form.useForm>[0]) => {
    if (!orgId || orgId.length < 8) return
    const targetForm = sourceForm || form
    const envUrl = targetForm.getFieldValue('env_url') || ''
    setLoadingStats(true)
    try {
      const res = await qaGenApi.getDagentStats(orgId, envUrl) as any
      setDagentStats(res.data || null)
    } catch (e: any) {
      console.error('加载统计信息失败:', e)
      message.error(`加载统计信息失败: ${e.message || '未知错误'}`)
      setDagentStats(null)
    } finally {
      setLoadingStats(false)
    }
  }

  const openReview = async (taskId: string) => {
    setReviewDrawer(taskId)
    setSelectedSection(null)
    setStatusFilter('all')
    setQuestions([])
    setQuestionPage(1)
    try {
      const [taskRes, secRes] = await Promise.all([
        qaGenApi.getTask(taskId) as any,
        qaGenApi.listSections(taskId) as any,
      ])
      setReviewTask(taskRes.data)
      setSections(secRes.data || [])
    } catch (e: any) {
      message.error('加载失败')
      setReviewDrawer(null)
    }
  }

  const loadQuestions = async (taskId: string, page = 1) => {
    setQuestionLoading(true)
    try {
      const res = await qaGenApi.listQuestions(taskId, {
        status: statusFilter === 'all' ? undefined : statusFilter,
        section: selectedSection || undefined,
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
  }, [reviewDrawer, statusFilter, selectedSection])

  const refreshReview = async () => {
    if (!reviewDrawer) return
    const [taskRes, secRes] = await Promise.all([
      qaGenApi.getTask(reviewDrawer) as any,
      qaGenApi.listSections(reviewDrawer) as any,
    ])
    setReviewTask(taskRes.data)
    setSections(secRes.data || [])
    loadQuestions(reviewDrawer, questionPage)
  }

  const handleApprove = async (id: string) => {
    await qaGenApi.approveQuestion(id)
    refreshReview()
  }

  const handleReject = async (id: string) => {
    await qaGenApi.rejectQuestion(id)
    refreshReview()
  }

  const handleEdit = async (vals: any) => {
    if (!editingQ) return
    await qaGenApi.editQuestion(editingQ.id, vals)
    setEditingQ(null)
    message.success('已保存并通过')
    refreshReview()
  }

  const handleBatchApprove = async (minQuality: number) => {
    if (!reviewDrawer) return
    await qaGenApi.batchApprove(reviewDrawer, minQuality)
    message.success('批量通过完成')
    refreshReview()
  }

  const handleCreateEvalTask = async () => {
    if (!reviewDrawer) return
    try {
      const res = await qaGenApi.createDataset(reviewDrawer, {
        name: `从QA生成任务导入-${reviewTask?.name || reviewDrawer.slice(0, 8)}`,
        knowledge_hub_id: '',
        description: `从问题生成任务 ${reviewTask?.name || reviewDrawer} 导入`,
      }) as any
      const datasetId = res.data?.dataset_id
      message.success('数据集创建成功')
      // 跳转到评测任务创建页面，并传递 datasetId
      navigate(`/task?dataset_id=${datasetId}`)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || e?.message || '创建失败')
    }
  }

  const handleAutoCreateEvalTask = async () => {
    if (!reviewDrawer) return
    const vals = await evalTaskForm.validateFields()
    setEvalSubmitting(true)
    try {
      // 1. 创建数据集
      const datasetRes = await qaGenApi.createDataset(reviewDrawer, {
        name: vals.name || `从QA生成任务导入-${reviewTask?.name || reviewDrawer.slice(0, 8)}`,
        knowledge_hub_id: vals.knowledge_hub_id,
        description: `从问题生成任务 ${reviewTask?.name || reviewDrawer} 导入`,
      }) as any
      const datasetId = datasetRes.data?.dataset_id
      message.success('数据集创建成功')

      // 2. 创建评测任务
      const taskData = {
        name: vals.name || `评测任务-${reviewTask?.name || reviewDrawer.slice(0, 8)}`,
        dataset_id: datasetId,
        platform_config_id: vals.platform_config_id,
        judge_config_id: vals.judge_config_id,
        agent_id: vals.agent_id,
        knowledge_hub_id: vals.knowledge_hub_id,
        top_k: vals.top_k,
        concurrency: vals.concurrency,
        selected_metrics: vals.selected_metrics,
        eval_retrieval: vals.selected_metrics.some((m: string) => ['hit_rate', 'mrr', 'ndcg', 'context_precision', 'context_recall'].includes(m)),
        eval_generation: vals.selected_metrics.some((m: string) => ['faithfulness', 'answer_relevance', 'answer_correctness', 'groundedness'].includes(m)),
      }
      await taskApi.run(taskData)
      message.success('评测任务创建成功，已开始执行')
      setEvalTaskModal(false)
      evalTaskForm.resetFields()
      // 可选：跳转到任务列表或报告页面
      navigate('/task')
    } catch (e: any) {
      message.error(e?.response?.data?.detail || e?.message || '创建失败')
    } finally {
      setEvalSubmitting(false)
    }
  }

  const handleCreateSingleJumpTask = async () => {
    if (!reviewDrawer) return
    // 直接下载 MD 文件
    window.open(qaGenApi.exportMd(reviewDrawer), '_blank')
    message.info('MD 文件已生成，请在单跳召回测试页面手动上传')
    navigate('/single-jump')
  }

  const handleAutoCreateSingleJumpTask = async () => {
    if (!reviewDrawer) return
    const vals = await singleJumpForm.validateFields()
    setSingleJumpSubmitting(true)
    try {
      // 0. 检查是否有已通过的问题
      if (!reviewTask?.approved || reviewTask.approved === 0) {
        throw new Error('没有已通过的问题，请先审核通过一些问题')
      }

      // 1. 测试MD文件导出URL是否可以访问
      const exportUrl = qaGenApi.exportMd(reviewDrawer)
      console.log('MD文件导出URL:', exportUrl)

      // 2. 直接使用axios下载文件，避免fetch跨域问题
      try {
        // 尝试直接使用API调用，看看后端是否正常工作
        const testRes = await fetch(exportUrl)
        if (!testRes.ok) {
          console.error('MD文件导出测试失败:', testRes.status, testRes.statusText)
          throw new Error(`MD文件导出失败: ${testRes.status} ${testRes.statusText}`)
        }

        // 3. 创建FormData并手动添加文件流
        const formData = new FormData()

        // 将导出URL直接作为file参数传递给后端
        // 让后端自己处理文件下载
        formData.append('name', vals.name || `从QA生成任务导入-${reviewTask?.name || reviewDrawer.slice(0, 8)}`)
        formData.append('env_url', vals.env_url)
        formData.append('org_id', vals.org_id)
        formData.append('d_user_id', vals.d_user_id || 'test')
        formData.append('agent_id', vals.agent_id || '')
        formData.append('top_k', String(vals.top_k ?? 64))
        formData.append('recall_top_k', String(vals.recall_top_k ?? 64))
        formData.append('concurrency', String(vals.concurrency ?? 5))
        formData.append('cross_chunk', String(vals.cross_chunk ?? true))
        formData.append('qa_gen_task_id', reviewDrawer) // 添加QA生成任务ID，让后端知道从哪里获取数据

        console.log('提交单跳召回测试任务，QA生成任务ID:', reviewDrawer, '文件名:', reviewTask?.name)

        // 调用一个新的API端点，让后端处理从QA生成任务创建单跳测试
        // 而不是让前端下载再上传
        const response = await fetch('/api/single-jump/task/from-qa-gen', {
          method: 'POST',
          body: formData,
        })

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}))
          throw new Error(errorData.detail || `创建失败: ${response.status}`)
        }

        message.success('单跳召回测试任务创建成功，已开始执行')
        setSingleJumpTaskModal(false)
        singleJumpForm.resetFields()
        navigate('/single-jump')
      } catch (fetchError: any) {
        console.error('API调用失败:', fetchError)
        // 如果新API端点不存在，回退到原始方法
        message.warning('使用新API失败，尝试原始方法...')

        // 回退到原始方法：下载文件再上传
        const mdUrl = exportUrl
        const response = await fetch(mdUrl)
        if (!response.ok) {
          throw new Error(`下载MD文件失败: ${response.status}`)
        }
        const mdContent = await response.text()

        if (!mdContent || mdContent.trim().length === 0) {
          throw new Error('下载的MD文件内容为空')
        }

        const fileName = `qa_${reviewTask?.name || reviewDrawer.slice(0, 8)}.md`.replace(/\s+/g, '_')
        const mdFile = new File([mdContent], fileName, { type: 'text/markdown' })

        const formData = new FormData()
        formData.append('file', mdFile)
        formData.append('name', vals.name || `从QA生成任务导入-${reviewTask?.name || reviewDrawer.slice(0, 8)}`)
        formData.append('env_url', vals.env_url)
        formData.append('org_id', vals.org_id)
        formData.append('d_user_id', vals.d_user_id || 'test')
        formData.append('agent_id', vals.agent_id || '')
        formData.append('top_k', String(vals.top_k ?? 64))
        formData.append('recall_top_k', String(vals.recall_top_k ?? 64))
        formData.append('concurrency', String(vals.concurrency ?? 5))
        formData.append('cross_chunk', String(vals.cross_chunk ?? true))

        await singleJumpApi.createTask(formData)
        message.success('单跳召回测试任务创建成功，已开始执行')
        setSingleJumpTaskModal(false)
        singleJumpForm.resetFields()
        navigate('/single-jump')
      }
    } catch (e: any) {
      console.error('创建单跳召回测试任务失败:', e)
      message.error(e?.response?.data?.detail || e?.message || '创建失败')
    } finally {
      setSingleJumpSubmitting(false)
    }
  }

  // ── 任务列表列 ──────────────────────────────────────────────────────────────
  const taskColumns = [
    { title: '任务名称', dataIndex: 'name', ellipsis: true, width: 200 },
    { title: '状态', dataIndex: 'status', width: 90, render: (v: string) => <StatusTag status={v} /> },
    {
      title: '进度', width: 160,
      render: (_: any, r: any) => r.status === 'running'
        ? <Progress percent={r.total ? Math.round(r.progress / r.total * 100) : 0} size="small" />
        : r.status === 'done'
          ? <Text type="success">{r.total} 章节完成</Text>
          : r.status === 'failed'
            ? <Tooltip title={r.error_message}><Text type="danger">失败</Text></Tooltip>
            : <Text type="secondary">-</Text>
    },
    {
      title: '问题数 / 已通过', width: 130,
      render: (_: any, r: any) => r.status === 'done'
        ? <Text>{r.approved ?? '-'} / <Text type="secondary">{r.total * 5}≈</Text></Text>
        : '-'
    },
    { title: '创建时间', dataIndex: 'created_at', width: 160, render: (v: string) => v?.slice(0, 19) },
    {
      title: '操作', width: 140,
      render: (_: any, r: any) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} disabled={r.status !== 'done'}
            onClick={() => openReview(r.id)}>审核</Button>
          <Popconfirm title="确认删除？" onConfirm={async () => { await qaGenApi.deleteTask(r.id); loadTasks() }}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      )
    },
  ]

  // ── 章节列表列 ──────────────────────────────────────────────────────────────
  const sectionColumns = [
    {
      title: '章节路径', dataIndex: 'section_path', ellipsis: true,
      render: (v: string) => (
        <Button type="link" size="small" style={{ padding: 0, textAlign: 'left', height: 'auto' }}
          onClick={() => setSelectedSection(v === selectedSection ? null : v)}>
          {v}
        </Button>
      )
    },
    { title: '总数', dataIndex: 'total', width: 60 },
    { title: '已通过', dataIndex: 'approved', width: 70,
      render: (v: number, r: any) => <Text type={v === r.total ? 'success' : 'secondary'}>{v}</Text> },
    { title: '待审核', dataIndex: 'pending', width: 70,
      render: (v: number) => v > 0 ? <Badge count={v} size="small" /> : <Text type="secondary">0</Text> },
    { title: '重复', dataIndex: 'duplicates', width: 60,
      render: (v: number) => v > 0 ? <Tag color="orange">{v}</Tag> : '-' },
    { title: '平均质量', dataIndex: 'avg_quality', width: 80,
      render: (v: number) => <QualityBadge score={v} /> },
  ]

  const statusOptions = [
    { label: '全部', value: 'all' },
    { label: '待审核', value: 'pending' },
    { label: '已通过', value: 'approved' },
    { label: '已拒绝', value: 'rejected' },
  ]

  return (
    <div>
      {/* Tab 切换 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Segmented
          value={activeTab}
          onChange={(v) => setActiveTab(v as 'generate' | 'loop')}
          options={[
            { label: '问题生成', value: 'generate', icon: <BulbOutlined /> },
            { label: '循环测试', value: 'loop', icon: <SyncOutlined /> },
          ]}
        />
        <Space>
          {activeTab === 'generate' ? (
            <>
              {selectedTaskKeys.length > 0 && (
                <Button danger icon={<DeleteOutlined />} onClick={handleBatchDeleteTasks}>
                  批量删除 ({selectedTaskKeys.length})
                </Button>
              )}
              <Button icon={<ReloadOutlined />} onClick={loadTasks}>刷新</Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModal(true)}>新建生成任务</Button>
            </>
          ) : (
            <>
              {selectedLoopTaskKeys.length > 0 && (
                <Button danger icon={<DeleteOutlined />} onClick={handleBatchDeleteLoopTasks}>
                  批量删除 ({selectedLoopTaskKeys.length})
                </Button>
              )}
              <Button icon={<ReloadOutlined />} onClick={loadLoopTasks}>刷新</Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setLoopCreateModal(true)}>新建循环任务</Button>
            </>
          )}
        </Space>
      </div>

      {activeTab === 'generate' ? (
        <>
          <Table
            rowKey="id"
            dataSource={tasks}
            columns={taskColumns}
            loading={loading}
            size="small"
            pagination={{ pageSize: 10 }}
            rowSelection={{
              selectedRowKeys: selectedTaskKeys,
              onChange: setSelectedTaskKeys,
            }}
          />

      {/* 新建任务弹窗 */}
      <Modal
        title="新建问题生成任务"
        open={createModal}
        onOk={handleCreate}
        onCancel={() => {
          setCreateModal(false)
          form.resetFields()
          setFileList([])
          setDagentStats(null)
          setDataSource('file')
        }}
        confirmLoading={submitting}
        width={560}
      >
        <Form form={form} layout="vertical"
          initialValues={{ questions_per_section: 5, quality_threshold: 0.6, include_multimodal: true }}>
          {/* 数据来源切换 */}
          <Form.Item label="数据来源">
            <Radio.Group value={dataSource} onChange={e => {
              setDataSource(e.target.value)
              setDagentStats(null)
            }}>
              <Radio value="file"><UploadOutlined /> 上传 MD 文件</Radio>
              <Radio value="dagent"><DatabaseOutlined /> 从 Dagent 知识库导入</Radio>
            </Radio.Group>
          </Form.Item>

          <Form.Item name="name" label="任务名称">
            <Input placeholder={dataSource === 'file' ? '可选，默认使用文件名' : '可选，默认使用组织 ID'} />
          </Form.Item>
          <Form.Item name="judge_config_id" label="LLM 配置" rules={[{ required: true, message: '请选择 LLM 配置' }]}
            tooltip="用于生成问题的 LLM，在配置管理中添加">
            <Select options={judgeOptions} placeholder="请选择" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="questions_per_section" label="每段落问题数">
                <InputNumber min={1} max={20} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="quality_threshold" label="自动通过质量阈值"
                tooltip="LLM 自评质量分 >= 阈值时自动通过，无需人工审核">
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
              <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
                支持知识库原始 MD 文件，按 ## 标题自动切分章节
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
                  onSearch={(v) => loadDagentStats(v)}
                />
              </Form.Item>

              {dagentStats && (
                <div style={{
                  background: '#f6ffed', border: '1px solid #b7eb8f',
                  borderRadius: 6, padding: '10px 14px', marginBottom: 16,
                }}>
                  <Row gutter={16}>
                    <Col span={6}><Statistic title="文件数" value={dagentStats.file_count ?? 0} valueStyle={{ fontSize: 18 }} /></Col>
                    <Col span={6}><Statistic title="段落数" value={dagentStats.paragraph_count ?? 0} valueStyle={{ fontSize: 18 }} /></Col>
                    <Col span={6}><Statistic title="含图段落" value={dagentStats.paragraphs_with_pic_text ?? 0} valueStyle={{ fontSize: 18 }} /></Col>
                    <Col span={6}><Statistic title="总图片" value={dagentStats.total_images ?? 0} valueStyle={{ fontSize: 18 }} /></Col>
                  </Row>
                </div>
              )}

              <Form.Item name="file_ids" label="选择文件"
                tooltip="选择要生成问题的文件，留空则全量导入所有已处理完成的文件">
                <div style={{ marginBottom: 8 }}>
                  <Segmented
                    size="small"
                    value={fileSelectorMode}
                    onChange={(v) => setFileSelectorMode(v as 'list' | 'tree')}
                    options={[
                      { label: '树形视图', value: 'tree' },
                      { label: '列表视图', value: 'list' },
                    ]}
                  />
                </div>
                {fileSelectorMode === 'tree' ? (
                  <DagentTreeSelector
                    orgId={form.getFieldValue('org_id') || ''}
                    envUrl={form.getFieldValue('env_url') || ''}
                    disabled={!form.getFieldValue('org_id')}
                    value={form.getFieldValue('file_ids')?.split(',').filter(Boolean) || []}
                    onChange={(fileIds) => form.setFieldsValue({ file_ids: fileIds.join(',') })}
                  />
                ) : (
                  <DagentFileSelector
                    orgId={form.getFieldValue('org_id') || ''}
                    envUrl={form.getFieldValue('env_url') || ''}
                    disabled={!form.getFieldValue('org_id')}
                  />
                )}
              </Form.Item>

              <Form.Item name="include_multimodal" label="生成图文结合问题" valuePropName="checked"
                tooltip="利用 Dagent 已生成的图片语义描述，生成图文结合的问题">
                <Switch defaultChecked />
              </Form.Item>
            </>
          )}
        </Form>
      </Modal>

      {/* 审核抽屉 */}
      <Drawer
        title={`问题审核 — ${reviewTask?.name || ''}`}
        open={!!reviewDrawer}
        onClose={() => { setReviewDrawer(null); setReviewTask(null) }}
        width="90%"
        styles={{ body: { padding: '16px 24px', display: 'flex', flexDirection: 'column', height: '100%' } }}
        extra={
          <Space>
            <Button icon={<DownloadOutlined />}
              onClick={() => reviewDrawer && window.open(qaGenApi.exportMd(reviewDrawer), '_blank')}
              disabled={!reviewTask?.approved}>
              导出已通过问题 {reviewTask?.approved ? `(${reviewTask.approved} 条)` : ''}
            </Button>
            <Button icon={<RocketOutlined />}
              onClick={() => setCreateTaskModal(true)}
              disabled={!reviewTask?.approved}>
              新建任务
            </Button>
          </Space>
        }
      >
        {!reviewTask ? <Spin /> : (
          <div style={{ display: 'flex', gap: 16, height: '100%', overflow: 'hidden' }}>
            {/* 左侧：章节列表 */}
            <div style={{ width: 340, flexShrink: 0, overflow: 'auto' }}>
              <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Text strong>章节列表（{sections.length} 个）</Text>
                {selectedSection && (
                  <Button size="small" onClick={() => setSelectedSection(null)}>清除筛选</Button>
                )}
              </div>
              <Table
                rowKey="section_path"
                dataSource={sections}
                columns={sectionColumns}
                size="small"
                pagination={false}
                scroll={{ y: 'calc(100vh - 260px)' }}
                rowClassName={r => r.section_path === selectedSection ? 'ant-table-row-selected' : ''}
              />
            </div>

            {/* 右侧：问题列表 */}
            <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
              {/* 工具栏 */}
              <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
                <Space wrap>
                  <Segmented
                    options={statusOptions}
                    value={statusFilter}
                    onChange={v => { setStatusFilter(v as string); setQuestionPage(1) }}
                  />
                  {selectedSection && (
                    <Tag color="blue" closable onClose={() => setSelectedSection(null)}>
                      {selectedSection.split('/').pop()}
                    </Tag>
                  )}
                </Space>
                <Space>
                  <Button size="small" icon={<ThunderboltOutlined />}
                    onClick={() => handleBatchApprove(0.6)}>
                    通过高质量(≥0.6)
                  </Button>
                  <Button size="small" onClick={() => handleBatchApprove(0)}>
                    全部通过
                  </Button>
                </Space>
              </div>

              {/* 问题卡片列表 */}
              <div style={{ flex: 1, overflow: 'auto' }}>
                <Spin spinning={questionLoading}>
                  {questions.length === 0 && !questionLoading
                    ? <Empty description="暂无问题" />
                    : questions.map(q => (
                      <QuestionCard
                        key={q.id}
                        q={q}
                        onApprove={() => handleApprove(q.id)}
                        onReject={() => handleReject(q.id)}
                        onEdit={() => setEditingQ(q)}
                      />
                    ))
                  }
                </Spin>
              </div>

              {/* 分页 */}
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
          </div>
        )}
      </Drawer>

      {/* 新建任务选择模态框 */}
      <Modal
        title="新建任务"
        open={createTaskModal}
        onCancel={() => setCreateTaskModal(false)}
        footer={null}
        width={400}
      >
        <div style={{ textAlign: 'center', padding: '20px 0' }}>
          <p style={{ marginBottom: 24 }}>选择要创建的任务类型，将已通过的问题导入：</p>
          <Space direction="vertical" size={16}>
            <Button
              type="primary"
              size="large"
              block
              icon={<PlayCircleOutlined />}
              onClick={() => {
                setSelectedTaskType('eval');
                setCreateTaskModal(false);
                setEvalTaskModal(true);
              }}
            >
              创建评测任务
            </Button>
            <Button
              size="large"
              block
              icon={<AimOutlined />}
              onClick={() => {
                setCreateTaskModal(false);
                setSingleJumpTaskModal(true);
              }}
            >
              创建单跳召回测试
            </Button>
          </Space>
        </div>
      </Modal>

      {/* 自动创建评测任务弹窗 */}
      <Modal
        title="自动创建评测任务"
        open={evalTaskModal}
        onOk={handleAutoCreateEvalTask}
        onCancel={() => { setEvalTaskModal(false); evalTaskForm.resetFields(); }}
        confirmLoading={evalSubmitting}
        width={600}
      >
        <Form form={evalTaskForm} layout="vertical">
          <Form.Item name="name" label="任务名称" initialValue={`从QA生成任务导入-${reviewTask?.name || reviewDrawer?.slice(0, 8) || ''}`}>
            <Input />
          </Form.Item>
          <Form.Item name="platform_config_id" label="平台配置" rules={[{ required: true, message: '请选择平台配置' }]}>
            <Select options={platformOptions} placeholder="请选择平台配置" />
          </Form.Item>
          <Form.Item name="judge_config_id" label="Judge 模型" rules={[{ required: true, message: '请选择 Judge 模型' }]}
            initialValue={reviewTask?.judge_config_id}>
            <Select options={judgeOptions} placeholder="请选择 Judge 模型" />
          </Form.Item>
          <Form.Item name="agent_id" label="Agent ID" rules={[{ required: true, message: '请输入 Agent ID' }]}>
            <Input placeholder="请输入 Agent ID" />
          </Form.Item>
          <Form.Item name="knowledge_hub_id" label="知识库 ID" rules={[{ required: true, message: '请输入知识库 ID' }]}>
            <Input placeholder="请输入知识库 ID" />
          </Form.Item>
          <Form.Item name="top_k" label="Top K" initialValue={10}>
            <InputNumber min={1} max={50} />
          </Form.Item>
          <Form.Item name="concurrency" label="并发数" initialValue={3}>
            <InputNumber min={1} max={10} />
          </Form.Item>
          <Form.Item name="selected_metrics" label="评测指标" initialValue={['hit_rate', 'mrr', 'ndcg', 'context_precision', 'context_recall', 'faithfulness', 'answer_relevance', 'answer_correctness', 'groundedness']}>
            <Checkbox.Group style={{ width: '100%' }}>
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontWeight: 'bold', marginBottom: 8, color: '#1677ff' }}>检索层指标</div>
                <Space direction="vertical" size={4}>
                  {['hit_rate', 'mrr', 'ndcg', 'context_precision', 'context_recall'].map(key => (
                    <Checkbox key={key} value={key}>
                      {metricCn(key)}
                    </Checkbox>
                  ))}
                </Space>
              </div>
              <div>
                <div style={{ fontWeight: 'bold', marginBottom: 8, color: '#722ed1' }}>生成层指标</div>
                <Space direction="vertical" size={4}>
                  {['faithfulness', 'answer_relevance', 'answer_correctness', 'groundedness'].map(key => (
                    <Checkbox key={key} value={key}>
                      {metricCn(key)}
                    </Checkbox>
                  ))}
                </Space>
              </div>
            </Checkbox.Group>
          </Form.Item>
        </Form>
      </Modal>

      {/* 自动创建单跳召回测试弹窗 */}
      <Modal
        title="自动创建单跳召回测试"
        open={singleJumpTaskModal}
        onOk={handleAutoCreateSingleJumpTask}
        onCancel={() => { setSingleJumpTaskModal(false); singleJumpForm.resetFields(); }}
        confirmLoading={singleJumpSubmitting}
        width={560}
      >
        <Form form={singleJumpForm} layout="vertical" initialValues={{ top_k: 64, recall_top_k: 64, concurrency: 20, cross_chunk: true, d_user_id: 'test' }}>
          <Form.Item name="name" label="任务名称" initialValue={`从QA生成任务导入-${reviewTask?.name || reviewDrawer?.slice(0, 8) || ''}`}>
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
              options={singleJumpAgentOptions}
              loading={singleJumpAgentOptionsLoading}
              disabled={!singleJumpOrgId || !singleJumpEnvUrl}
              notFoundContent={!singleJumpOrgId || !singleJumpEnvUrl ? '请先填写 Org ID 和环境地址' : '未找到 Agent'}
            />
          </Form.Item>
          <Form.Item name="d_user_id" label="User ID"
            tooltip="请求头 d-user-id，默认 test">
            <Input />
          </Form.Item>
          <Row gutter={12}>
            <Col span={6}>
              <Form.Item name="top_k" label="命中判断 Top K">
                <InputNumber min={1} max={200} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="recall_top_k" label="召回数量 Top K">
                <InputNumber min={1} max={500} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="concurrency" label="并发数">
                <InputNumber min={1} max={50} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="cross_chunk" label="跨切片模式" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      {/* 编辑弹窗 */}
      {editingQ && (
        <EditModal
          question={editingQ}
          onOk={handleEdit}
          onCancel={() => setEditingQ(null)}
        />
      )}
    </>
  ) : (
    <>
      {/* 循环测试任务列表 */}
      <Table
        rowKey="id"
        dataSource={loopTasks}
        columns={[
          { title: '任务名称', dataIndex: 'name', ellipsis: true },
          {
            title: '状态',
            dataIndex: 'status',
            width: 140,
            render: (v: string, r: any) => (
              <Space direction="vertical" size={4}>
                <LoopStatusTag status={v} />
                {v === 'failed' && (
                  <Tooltip title={`技术错误: ${r.error_message || '未知错误'}`}>
                    <Text type="danger" style={{ fontSize: 12, cursor: 'pointer' }}>
                      <WarningOutlined /> 第{r.current_round}轮失败
                    </Text>
                  </Tooltip>
                )}
              </Space>
            )
          },
          { title: '轮次', dataIndex: 'current_round', width: 70, render: (v: number, r: any) => `${v}/${r.max_rounds || '∞'}` },
          { title: '已通过', dataIndex: 'total_approved', width: 80 },
          { title: '重复', dataIndex: 'total_duplicates', width: 70 },
          { title: '召回率', dataIndex: 'recall_rate', width: 80, render: (v: number) => v ? `${(v * 100).toFixed(1)}%` : '-' },
          { title: '文件命中率', dataIndex: 'file_hit_rate', width: 100, render: (v: number) => v ? `${(v * 100).toFixed(1)}%` : '-' },
          { title: '创建时间', dataIndex: 'created_at', width: 160, render: (v: string) => v?.slice(0, 19) },
          {
            title: '操作', width: 180,
            render: (_: any, r: any) => (
              <Space>
                <Button size="small" icon={<EyeOutlined />} onClick={() => openLoopDetail(r.id)}>查看</Button>
                {r.status === 'running' && (
                  <Button size="small" icon={<PauseCircleOutlined />} onClick={() => handlePauseLoop(r.id)}>暂停</Button>
                )}
                {r.status === 'paused' && (
                  <Button size="small" type="primary" icon={<PlayCircleOutlined />} onClick={() => handleResumeLoop(r.id)}>继续</Button>
                )}
                {(r.status === 'running' || r.status === 'paused') && (
                  <Button size="small" danger icon={<StopOutlined />} onClick={() => handleStopLoop(r.id)}>停止</Button>
                )}
                <Popconfirm title="确认删除？" onConfirm={() => handleDeleteLoop(r.id)}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>
            )
          },
        ]}
        loading={loopLoading}
        size="small"
        pagination={{ pageSize: 10 }}
        rowSelection={{
          selectedRowKeys: selectedLoopTaskKeys,
          onChange: setSelectedLoopTaskKeys,
        }}
      />

      {/* 循环任务详情 Drawer */}
      <Drawer
        title={loopDetail?.name}
        width={900}
        open={!!loopDetailDrawer}
        onClose={() => setLoopDetailDrawer(null)}
      >
        {loopDetail && (
          <>
            {/* 操作按钮 */}
            <Space style={{ marginBottom: 16 }}>
              {loopDetail.status === 'running' && (
                <Button icon={<PauseCircleOutlined />} onClick={() => handlePauseLoop(loopDetail.id)}>暂停</Button>
              )}
              {loopDetail.status === 'paused' && (
                <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => handleResumeLoop(loopDetail.id)}>继续</Button>
              )}
              {(loopDetail.status === 'running' || loopDetail.status === 'paused') && (
                <Button danger icon={<StopOutlined />} onClick={() => handleStopLoop(loopDetail.id)}>停止</Button>
              )}
            </Space>

            {/* 错误提示 */}
            {loopDetail.status === 'failed' && loopDetail.error_message && (
              <Card size="small" style={{ marginBottom: 16, borderColor: '#ff4d4f', background: '#fff2f0' }}>
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Text type="danger" strong>
                    <WarningOutlined /> 任务失败：第 {loopDetail.current_round} 轮出现错误
                  </Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    技术错误信息: {loopDetail.error_message}
                  </Text>
                </Space>
              </Card>
            )}

            {/* 统计卡片 */}
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={4}>
                <Card size="small">
                  <Statistic title="总生成" value={loopDetail.total_generated || 0} />
                </Card>
              </Col>
              <Col span={4}>
                <Card size="small">
                  <Statistic title="已通过" value={loopDetail.total_approved || 0} />
                </Card>
              </Col>
              <Col span={4}>
                <Card size="small">
                  <Statistic title="重复" value={loopDetail.total_duplicates || 0} />
                </Card>
              </Col>
              <Col span={4}>
                <Card size="small">
                  <Statistic title="已测试" value={loopDetail.total_tested || 0} />
                </Card>
              </Col>
              <Col span={4}>
                <Card size="small">
                  <Statistic title="召回率" value={loopDetail.recall_rate ? `${(loopDetail.recall_rate * 100).toFixed(1)}%` : '-'} />
                </Card>
              </Col>
              <Col span={4}>
                <Card size="small">
                  <Statistic title="文件命中率" value={loopDetail.file_hit_rate ? `${(loopDetail.file_hit_rate * 100).toFixed(1)}%` : '-'} />
                </Card>
              </Col>
            </Row>

            {/* 导出按钮 */}
            <Card size="small" title="导出问答集" style={{ marginBottom: 16 }}>
              <Space wrap>
                <Button onClick={() => handleExport('all')}>全部 (MD)</Button>
                <Button onClick={() => handleExport('hit')}>命中成功 (MD)</Button>
                <Button onClick={() => handleExport('file_miss')}>文件未命中 (MD)</Button>
                <Button onClick={() => handleExport('recall_failed')}>召回失败 (MD)</Button>
                <Button onClick={() => handleExportJson('all')}>全部 (JSON)</Button>
              </Space>
            </Card>

            {/* 轮次时间线 */}
            <Card size="small" title="轮次记录" loading={loopDetailLoading}>
              <Table
                rowKey="id"
                dataSource={loopRounds}
                size="small"
                pagination={false}
                columns={[
                  { title: '轮次', dataIndex: 'round_number', width: 60 },
                  {
                    title: '当前环节', dataIndex: 'status', width: 150,
                    render: (v: string, record: any) => {
                      const stageMap: Record<string, { label: string; color: string }> = {
                        qa_generating:  { label: '生成问题中', color: 'processing' },
                        deduplicating:  { label: '去重检查中', color: 'processing' },
                        testing:        { label: '召回测试中', color: 'processing' },
                        done:           { label: '已完成',     color: 'success' },
                        failed:         { label: '失败',       color: 'error' },
                      }
                      const cfg = stageMap[v] || { label: v, color: 'default' }
                      const label = v === 'deduplicating' && record.dedup_progress
                        ? `${cfg.label} (${record.dedup_progress})`
                        : cfg.label
                      return <Tag color={cfg.color}>{label}</Tag>
                    }
                  },
                  { title: '生成', dataIndex: 'generated', width: 60 },
                  { title: '通过', dataIndex: 'approved', width: 60 },
                  { title: '重复', dataIndex: 'duplicates', width: 60 },
                  { title: '召回', dataIndex: 'recalled', width: 60 },
                  { title: '命中', dataIndex: 'file_hit', width: 60 },
                  { title: '开始时间', dataIndex: 'started_at', render: (v: string) => v?.slice(0, 19) || '-' },
                  { title: '结束时间', dataIndex: 'finished_at', render: (v: string) => v?.slice(0, 19) || '-' },
                ]}
              />
            </Card>
          </>
        )}
      </Drawer>

      {/* 新建循环任务弹窗 */}
      <Modal
        title="新建循环测试任务"
        open={loopCreateModal}
        onOk={handleCreateLoopTask}
        onCancel={() => {
          setLoopCreateModal(false)
          loopForm.resetFields()
          setDagentStats(null)
        }}
        confirmLoading={loopSubmitting}
        width={600}
      >
        <Form form={loopForm} layout="vertical"
          initialValues={{ questions_per_section: 5, quality_threshold: 0.6, include_multimodal: true, top_k: 64, recall_top_k: 64, concurrency: 20, cross_chunk: true, max_rounds: 0, max_questions: 0 }}>
          <Form.Item name="name" label="任务名称">
            <Input placeholder="可选，默认使用组织ID" />
          </Form.Item>
          <Form.Item name="env_url" label="Agent 环境地址" rules={[{ required: true }]}>
            <Input placeholder="https://dagent.d-robotics.cc" />
          </Form.Item>
          <Form.Item name="org_id" label="Dagent 组织 ID" rules={[{ required: true, message: '请输入组织ID' }]}>
            <Input.Search
              placeholder="a4d49699ba313815..."
              enterButton="查询"
              loading={loadingStats}
              onSearch={(v) => loadDagentStats(v, loopForm)}
            />
          </Form.Item>
          {dagentStats && (
            <div style={{ marginBottom: 16, padding: 12, background: '#f6ffed', border: '1px solid #b7eb8f', borderRadius: 4 }}>
              <div>文件数: <b>{dagentStats.file_count}</b> | 段落数: <b>{dagentStats.paragraph_count}</b></div>
            </div>
          )}
          <Form.Item name="agent_id" label="Agent（可选）"
            tooltip="选择要使用的 Agent 版本进行召回测试，为空时直接调用知识库搜索 API">
            <Select
              placeholder="请选择 Agent（可选）"
              allowClear
              showSearch
              options={loopAgentOptions}
              loading={loopAgentOptionsLoading}
              disabled={!loopOrgId || !loopEnvUrl}
              notFoundContent={!loopOrgId || !loopEnvUrl ? '请先填写 Org ID 和环境地址' : '未找到 Agent'}
            />
          </Form.Item>
          <Form.Item name="file_ids" label="选择文件（可选，不选则使用全部）">
            <div style={{ marginBottom: 8 }}>
              <Segmented
                size="small"
                value={fileSelectorMode}
                onChange={(v) => setFileSelectorMode(v as 'list' | 'tree')}
                options={[
                  { label: '树形视图', value: 'tree' },
                  { label: '列表视图', value: 'list' },
                ]}
              />
            </div>
            {fileSelectorMode === 'tree' ? (
              <DagentTreeSelector
                orgId={loopOrgId || ''}
                envUrl={loopEnvUrl || ''}
                disabled={!loopOrgId}
                value={loopForm.getFieldValue('file_ids')?.split(',').filter(Boolean) || []}
                onChange={(fileIds) => loopForm.setFieldsValue({ file_ids: fileIds.join(',') })}
              />
            ) : (
              <DagentFileSelector orgId={loopOrgId || ''} envUrl={loopEnvUrl || ''} />
            )}
          </Form.Item>
          <Form.Item name="judge_config_id" label="LLM 配置" rules={[{ required: true, message: '请选择LLM配置' }]}>
            <Select options={judgeOptions} placeholder="请选择" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="questions_per_section" label="每段落问题数">
                <InputNumber min={1} max={20} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="quality_threshold" label="质量阈值">
                <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="include_multimodal" label="图文问题" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={6}>
              <Form.Item name="top_k" label="命中判断 Top K">
                <InputNumber min={1} max={200} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="recall_top_k" label="召回数量 Top K">
                <InputNumber min={1} max={500} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="concurrency" label="并发数">
                <InputNumber min={1} max={50} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="cross_chunk" label="跨切片模式" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="max_rounds" label="最大轮次 (0=无限)">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="max_questions" label="最大问题数 (0=无限)">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </>
  )}
</div>
  )
}
