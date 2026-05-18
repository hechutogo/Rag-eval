import React, { useEffect, useRef, useState } from 'react'
import {
  Table, Button, Modal, Form, Input, InputNumber, Upload, Tag, Progress,
  Drawer, Card, Row, Col, Statistic, Space, Tooltip, Typography, message,
  Collapse, Badge, Segmented, Select,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, ReloadOutlined, UploadOutlined,
  SyncOutlined, CheckCircleOutlined, CloseCircleOutlined, MinusCircleOutlined,
  AimOutlined, BulbOutlined, SearchOutlined,
} from '@ant-design/icons'
import { multiHopApi } from '../../services/api'
import GenTab from './GenTab'

const { Text } = Typography

function StatusTag({ status }: { status: string }) {
  const map: Record<string, { color: string; icon?: React.ReactNode; label: string }> = {
    pending: { color: 'default',    label: '等待中' },
    running: { color: 'processing', icon: <SyncOutlined spin />, label: '运行中' },
    done:    { color: 'success',    label: '完成' },
    failed:  { color: 'error',      label: '失败' },
  }
  const cfg = map[status] || { color: 'default', label: status }
  return <Tag color={cfg.color} icon={cfg.icon}>{cfg.label}</Tag>
}

function HitTag({ full, partial }: { full: boolean; partial: boolean }) {
  if (full)    return <Tag color="success" icon={<CheckCircleOutlined />}>全命中</Tag>
  if (partial) return <Tag color="warning" icon={<MinusCircleOutlined />}>部分命中</Tag>
  return <Tag color="error" icon={<CloseCircleOutlined />}>未命中</Tag>
}

export default function MultiHop() {
  const [tasks, setTasks] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [createModal, setCreateModal] = useState(false)
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  const [fileList, setFileList] = useState<any[]>([])
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Agent 列表
  const [agentOptions, setAgentOptions] = useState<{ label: string; value: string; desc?: string }[]>([])
  const [loadingAgents, setLoadingAgents] = useState(false)

  // 报告 Drawer
  const [drawerTaskId, setDrawerTaskId] = useState<string | null>(null)
  const [summary, setSummary] = useState<any>(null)
  const [results, setResults] = useState<any[]>([])
  const [drawerLoading, setDrawerLoading] = useState(false)

  // 详情 Drawer
  const [detailResult, setDetailResult] = useState<any>(null)

  // 批量删除
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([])

  const loadTasks = async () => {
    setLoading(true)
    try {
      const res = await multiHopApi.listTasks() as any
      setTasks(res.data || [])
    } finally {
      setLoading(false)
    }
  }

  const loadAgents = async () => {
    const envUrl = form.getFieldValue('env_url')
    const orgId = form.getFieldValue('org_id')
    const dUserId = form.getFieldValue('d_user_id') || 'test'
    if (!envUrl || !orgId) { message.warning('请先填写环境地址和 Org ID'); return }
    setLoadingAgents(true)
    try {
      const res = await multiHopApi.listDagentAgents(envUrl, orgId, dUserId) as any
      const agents = res.data || []
      if (!agents.length) { message.warning('未找到可用的 Agent'); return }
      setAgentOptions(agents.map((a: any) => ({
        label: a.name || a.id,
        value: a.id,
        desc: a.description || a.type || '',
      })))
      message.success(`找到 ${agents.length} 个 Agent`)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || e?.message || '拉取 Agent 列表失败')
    } finally {
      setLoadingAgents(false)
    }
  }

  const loadReport = async (taskId: string) => {
    setDrawerLoading(true)
    try {
      const [sumRes, resRes] = await Promise.all([
        multiHopApi.getSummary(taskId) as any,
        multiHopApi.getResults(taskId) as any,
      ])
      setSummary(sumRes.data)
      setResults(resRes.data || [])
    } finally {
      setDrawerLoading(false)
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
    if (!fileList.length) { message.error('请上传多跳问答 MD 文件'); return }
    setSubmitting(true)
    try {
      const fd = new FormData()
      fd.append('file', fileList[0].originFileObj)
      fd.append('name', vals.name || fileList[0].name)
      fd.append('env_url', vals.env_url)
      fd.append('org_id', vals.org_id)
      fd.append('agent_id', vals.agent_id)
      fd.append('llm_type', vals.llm_type || 'deepseek_v3')
      fd.append('d_user_id', vals.d_user_id || 'test')
      fd.append('top_k', String(vals.top_k ?? 10))
      fd.append('concurrency', String(vals.concurrency ?? 5))
      await multiHopApi.createTask(fd)
      message.success('任务已创建')
      setCreateModal(false)
      form.resetFields()
      setFileList([])
      loadTasks()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || e?.message || '创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await multiHopApi.deleteTask(id)
      message.success('已删除')
      loadTasks()
      if (drawerTaskId === id) setDrawerTaskId(null)
    } catch (e: any) {
      message.error(e?.message || '删除失败')
    }
  }

  const handleBatchDelete = () => {
    if (!selectedKeys.length) { message.warning('请先选择任务'); return }
    Modal.confirm({
      title: `确认删除选中的 ${selectedKeys.length} 个任务？`,
      okType: 'danger',
      okText: '确认删除',
      cancelText: '取消',
      async onOk() {
        await Promise.all(selectedKeys.map(id => multiHopApi.deleteTask(id as string)))
        message.success('批量删除成功')
        setSelectedKeys([])
        loadTasks()
        if (drawerTaskId && selectedKeys.includes(drawerTaskId)) setDrawerTaskId(null)
      },
    })
  }

  const openReport = (taskId: string) => {
    setDrawerTaskId(taskId)
    loadReport(taskId)
  }

  const columns = [
    { title: '任务名称', dataIndex: 'name', ellipsis: true },
    { title: '环境地址', dataIndex: 'env_url', ellipsis: true, width: 200 },
    { title: 'Org ID', dataIndex: 'org_id', ellipsis: true, width: 160 },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (v: string) => <StatusTag status={v} />,
    },
    {
      title: '进度', width: 160,
      render: (_: any, r: any) => r.status === 'running'
        ? <Progress percent={r.total ? Math.round(r.progress / r.total * 100) : 0} size="small" />
        : r.status === 'done'
          ? <Text type="success">{r.total} 题完成</Text>
          : r.status === 'failed'
            ? <Text type="danger">失败</Text>
            : '-',
    },
    { title: '创建时间', dataIndex: 'created_at', width: 160, render: (v: string) => v?.slice(0, 19) },
    {
      title: '操作', width: 140,
      render: (_: any, r: any) => (
        <Space>
          <Button size="small" disabled={r.status !== 'done'} onClick={() => openReport(r.id)}>报告</Button>
          <Button size="small" danger onClick={() => handleDelete(r.id)}>删除</Button>
        </Space>
      ),
    },
  ]

  const drawerTask = tasks.find(t => t.id === drawerTaskId)
  const [activeTab, setActiveTab] = useState<'test' | 'gen'>('test')

  return (
    <div>
      {/* 标题栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Segmented
          value={activeTab}
          onChange={v => setActiveTab(v as 'test' | 'gen')}
          options={[
            { label: '召回测试', value: 'test', icon: <AimOutlined /> },
            { label: '生成 Case', value: 'gen', icon: <BulbOutlined /> },
          ]}
        />
        {activeTab === 'test' && <Space>
          {selectedKeys.length > 0 && (
            <Button danger icon={<DeleteOutlined />} onClick={handleBatchDelete}>
              删除选中 ({selectedKeys.length})
            </Button>
          )}
          <Button icon={<ReloadOutlined />} onClick={loadTasks}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModal(true)}>新建测试</Button>
        </Space>}
      </div>

      {activeTab === 'gen' ? <GenTab /> : (
        <>
          {/* 任务列表 */}
          <Table
            rowKey="id"
            dataSource={tasks}
            columns={columns}
            loading={loading}
            size="small"
            rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
            pagination={{ pageSize: 20 }}
          />

          {/* 新建弹窗 */}
          <Modal
            title="新建多跳召回测试"
            open={createModal}
            onOk={handleCreate}
            onCancel={() => { setCreateModal(false); form.resetFields(); setFileList([]); setAgentOptions([]) }}
            confirmLoading={submitting}
            width={520}
          >
            <Form form={form} layout="vertical"
              initialValues={{ d_user_id: 'test', concurrency: 5 }}>
              <Form.Item name="name" label="任务名称">
                <Input placeholder="可选，默认使用文件名" />
              </Form.Item>
              <Form.Item name="env_url" label="Agent 环境地址" rules={[{ required: true }]}>
                <Input placeholder="https://your-dagent-env.com" />
              </Form.Item>
              <Form.Item name="org_id" label="Org ID" rules={[{ required: true }]}>
                <Input placeholder="cd6e121594984516..." />
              </Form.Item>
              <Form.Item name="d_user_id" label="User ID">
                <Input />
              </Form.Item>
              <Form.Item
                name="agent_id"
                label="Agent"
                rules={[{ required: true, message: '请选择 Agent' }]}
                tooltip="测试会调用 /agent/chat，由 Agent 自主决定搜几次知识库"
              >
                <Select
                  placeholder="填写环境地址和 Org ID 后点右侧按钮查询"
                  options={agentOptions.map(a => ({
                    label: (
                      <Space size={4}>
                        <span>{a.label}</span>
                        {a.desc && <Text type="secondary" style={{ fontSize: 11 }}>{a.desc}</Text>}
                      </Space>
                    ),
                    value: a.value,
                  }))}
                  notFoundContent={agentOptions.length === 0 ? '点击下方「查询 Agent」' : '无匹配'}
                  dropdownRender={menu => (
                    <div>
                      {menu}
                      <div style={{ padding: '6px 8px', borderTop: '1px solid #f0f0f0' }}>
                        <Button
                          size="small"
                          icon={<SearchOutlined />}
                          loading={loadingAgents}
                          onClick={loadAgents}
                          block
                        >
                          查询 Agent 列表
                        </Button>
                      </div>
                    </div>
                  )}
                />
              </Form.Item>
              <Form.Item
                name="llm_type"
                label="LLM 类型"
                tooltip="Agent 使用的 LLM，不同模型可用性取决于远程环境配置"
              >
                <Select
                  options={[
                    { label: 'DeepSeek V3', value: 'deepseek_v3' },
                    { label: 'DeepSeek R1', value: 'deepseek-r1' },
                    { label: 'Volc DeepSeek V3', value: 'volc_deepseek_v3_250324' },
                    { label: 'Azure GPT-4o', value: 'azure_openai_4o' },
                    { label: 'Azure GPT-4.1', value: 'azure/gpt-4.1' },
                    { label: 'Claude 3.5 Sonnet', value: 'aws/claude-3-5-sonnet' },
                  ]}
                />
              </Form.Item>
              <Row gutter={12}>
                <Col span={12}>
                  <Form.Item name="concurrency" label="并发数">
                    <InputNumber min={1} max={10} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item label="多跳问答 MD 文件" required>
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
                  格式参考：## MH1 / **问题:** / **答案:** / **Hop1:** section_path | 说明
                </div>
              </Form.Item>
            </Form>
          </Modal>

          {/* 报告 Drawer */}
          <Drawer
            title={drawerTask?.name}
            width="80%"
            open={!!drawerTaskId}
            onClose={() => setDrawerTaskId(null)}
          >
            {summary && (
              <>
                <Card size="small" style={{ marginBottom: 16 }}>
                  <Row gutter={16}>
                    <Col span={4}><Statistic title="总问题数" value={summary.total} /></Col>
                    <Col span={4}>
                      <Statistic title="全命中率" value={(summary.full_hit_rate * 100).toFixed(1)} suffix="%" valueStyle={{ color: '#52c41a' }} />
                    </Col>
                    <Col span={4}>
                      <Statistic title="部分命中率" value={(summary.partial_hit_rate * 100).toFixed(1)} suffix="%" valueStyle={{ color: '#faad14' }} />
                    </Col>
                    <Col span={4}>
                      <Statistic title="平均Hop命中" value={(summary.avg_hop_hit_rate * 100).toFixed(1)} suffix="%" />
                    </Col>
                    <Col span={4}>
                      <Statistic title="平均相似度" value={summary.avg_cosine_sim ?? '-'} precision={4} />
                    </Col>
                    <Col span={4}>
                      <Statistic title="平均延迟" value={summary.avg_latency_ms?.toFixed(0) ?? '-'} suffix="ms" />
                    </Col>
                  </Row>
                  {(summary.empty_count > 0 || summary.error_count > 0) && (
                    <div style={{ marginTop: 8 }}>
                      {summary.empty_count > 0 && <Tag color="warning">空召回 {summary.empty_count} 题</Tag>}
                      {summary.error_count > 0 && <Tag color="error">错误 {summary.error_count} 题</Tag>}
                    </div>
                  )}
                </Card>
                <Table
                  rowKey="id"
                  dataSource={results}
                  loading={drawerLoading}
                  size="small"
                  pagination={{ pageSize: 20 }}
                  columns={[
                    { title: 'ID', dataIndex: 'qid', width: 70 },
                    { title: '类型', dataIndex: 'type', width: 90,
                      render: (v: string) => {
                        const map: Record<string, string> = { comparison: '比较型', reasoning: '推理型', aggregation: '聚合型' }
                        return <Tag>{map[v] || v}</Tag>
                      }
                    },
                    { title: '问题', dataIndex: 'question', ellipsis: true },
                    { title: '命中', width: 110, render: (_: any, r: any) => <HitTag full={r.full_hit === 1} partial={r.partial_hit === 1} /> },
                    { title: 'Hop命中', width: 80, render: (_: any, r: any) => `${r.hop_hit_count}/${r.hop_count}` },
                    { title: '最佳相似度', dataIndex: 'best_cosine_sim', width: 100, render: (v: number) => v != null ? v.toFixed(4) : '-' },
                    { title: '延迟', dataIndex: 'latency_ms', width: 80, render: (v: number) => `${v}ms` },
                    { title: '操作', width: 70, render: (_: any, r: any) => <Button size="small" onClick={() => setDetailResult(r)}>详情</Button> },
                  ]}
                />
              </>
            )}
          </Drawer>

          {/* 问题详情 Drawer */}
          <Drawer
            title={
              <Space>
                <span>{detailResult?.qid}</span>
                {detailResult && (() => {
                  const typeMap: Record<string, { label: string; color: string; desc: string }> = {
                    comparison:  { label: '比较型', color: 'blue',   desc: '需对比多个文档中的同类信息' },
                    reasoning:   { label: '推理型', color: 'purple', desc: '需从多个文档逐步推导出结论' },
                    aggregation: { label: '聚合型', color: 'cyan',   desc: '需从多个文档收集同类信息汇总' },
                  }
                  const t = typeMap[detailResult.type] || { label: detailResult.type, color: 'default', desc: '' }
                  return (
                    <Tooltip title={t.desc}>
                      <Tag color={t.color} style={{ cursor: 'help' }}>{t.label}</Tag>
                    </Tooltip>
                  )
                })()}
              </Space>
            }
            width={620}
            open={!!detailResult}
            onClose={() => setDetailResult(null)}
          >
            {detailResult && (() => {
              const hops: any[] = detailResult.hops || []
              const actualHops: any[] = detailResult.actual_hops || []
              const retrieved: any[] = detailResult.retrieved || []

              // 期望 hop → 在合并召回列表中的排名
              const hopRankMap: Record<number, number> = {}
              hops.forEach((h, hi) => {
                if (!h.file_id) return
                const rank = retrieved.findIndex((r: any) => r.file_id === h.file_id)
                hopRankMap[hi] = rank >= 0 ? rank + 1 : 0
              })

              // 合并召回列表中每条属于哪个期望 hop
              const chunkHopMap: Record<number, number[]> = {}
              retrieved.forEach((chunk: any, ci) => {
                hops.forEach((h, hi) => {
                  if (h.file_id && h.file_id === chunk.file_id) {
                    if (!chunkHopMap[ci]) chunkHopMap[ci] = []
                    chunkHopMap[ci].push(hi + 1)
                  }
                })
              })

              // 诊断：Agent 无召回的原因
              const noActualHopReason: string | null = (() => {
                if (actualHops.length > 0) return null
                if (detailResult.error) return null  // 有 error 单独展示
                return 'Agent 未返回任何召回结果，可能原因：Agent ID 配置错误、网络超时，或该问题触发了 Agent 的拒答逻辑。请检查任务配置后重新运行。'
              })()

              return (
                <div>
                  {/* 问题 & 答案 */}
                  <Card size="small" style={{ marginBottom: 12 }}>
                    <div style={{ fontWeight: 500, marginBottom: 6 }}>{detailResult.question}</div>
                    <Text type="secondary" style={{ fontSize: 12 }}>参考答案：{detailResult.answer}</Text>
                    {detailResult.agent_answer && (
                      <div style={{ marginTop: 8, padding: '6px 10px', background: '#f0f5ff', borderRadius: 4, fontSize: 12 }}>
                        <Text type="secondary">Agent 回答：</Text>{detailResult.agent_answer}
                      </div>
                    )}
                  </Card>

                  {/* 期望跳链 */}
                  <Card
                    size="small"
                    style={{ marginBottom: 12 }}
                    title={
                      <Space>
                        <span>期望跳链（{hops.length} 跳）</span>
                        <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
                          — 回答此问题需要覆盖的文档
                        </Text>
                      </Space>
                    }
                  >
                    {hops.map((h: any, i: number) => {
                      const hit = h.hit
                      const hitAtHop = h.hit_at_hop
                      // 细化未命中原因
                      const missReason: string = (() => {
                        if (hit) return `第 ${hitAtHop} 跳命中`
                        if (!h.file_id) return '文件映射失败'
                        if (actualHops.length === 0) return 'Agent 无召回'
                        return '未召回'
                      })()
                      // 文件映射失败用橙色，其他未命中用红色
                      const missColor = !h.file_id ? '#fa8c16' : '#ff4d4f'
                      const rankColor = hit ? '#52c41a' : missColor
                      // 文件映射失败时背景用橙色系
                      const bgColor = hit ? '#f6ffed' : (!h.file_id ? '#fff7e6' : '#fff2f0')
                      const borderColor = hit ? '#b7eb8f' : (!h.file_id ? '#ffd591' : '#ffccc7')
                      return (
                        <div key={i} style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0 }}>
                            <div style={{
                              width: 26, height: 26, borderRadius: '50%', display: 'flex',
                              alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 600,
                              background: bgColor,
                              border: `2px solid ${rankColor}`,
                              color: rankColor,
                            }}>{i + 1}</div>
                            {i < hops.length - 1 && (
                              <div style={{ width: 2, flex: 1, minHeight: 16, background: '#f0f0f0', margin: '3px 0' }} />
                            )}
                          </div>
                          <div style={{
                            flex: 1, padding: '5px 10px', borderRadius: 6, marginBottom: 8,
                            background: bgColor,
                            border: `1px solid ${borderColor}`,
                          }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
                              <Space size={4}>
                                {hit ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : <CloseCircleOutlined style={{ color: missColor }} />}
                                <Text strong style={{ fontSize: 13 }}>Hop {i + 1}</Text>
                                <Text style={{ fontSize: 12 }}>{h.file_name || h.section_path}</Text>
                              </Space>
                              <span style={{ fontSize: 12, color: rankColor, fontWeight: 500 }}>{missReason}</span>
                            </div>
                            {!h.file_id && (
                              <div style={{ fontSize: 11, color: '#ad6800', marginBottom: 3 }}>
                                ⚠️ section_path「{h.section_path}」未能匹配到知识库中的任何文件，命中判断已跳过此跳
                              </div>
                            )}
                            {h.contribution && (
                              <div style={{ fontSize: 12, color: '#666' }}>📌 {h.contribution}</div>
                            )}
                          </div>
                        </div>
                      )
                    })}
                  </Card>

                  {/* Agent 无召回时的诊断提示 */}
                  {noActualHopReason && (
                    <Card
                      size="small"
                      style={{ marginBottom: 12, borderColor: '#faad14', background: '#fffbe6' }}
                      title={<Text style={{ color: '#ad6800' }}>⚠️ Agent 召回诊断</Text>}
                    >
                      <Text style={{ fontSize: 12, color: '#ad6800' }}>{noActualHopReason}</Text>
                    </Card>
                  )}

                  {/* 每跳召回详情 */}
                  {actualHops.length > 0 && actualHops.map((ah: any, hopIdx: number) => {
                    const docs: any[] = ah.retrieved || []
                    const hitHopNums = hops
                      .map((h: any, hi: number) => h.file_id && docs.some((d: any) => d.file_id === h.file_id) ? hi + 1 : null)
                      .filter(Boolean)
                    const hopColors = ['#1890ff', '#722ed1', '#13c2c2', '#fa8c16', '#eb2f96']
                    const color = hopColors[hopIdx % hopColors.length]
                    return (
                      <Card
                        key={hopIdx}
                        size="small"
                        style={{ marginBottom: 12, borderColor: color }}
                        title={
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <Space size={6}>
                              <div style={{
                                width: 24, height: 24, borderRadius: '50%', display: 'inline-flex',
                                alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700,
                                background: color, color: '#fff',
                              }}>{ah.hop_index}</div>
                              <span style={{ fontWeight: 600 }}>第 {ah.hop_index} 跳</span>
                              {hitHopNums.map((n: any) => (
                                <Tag key={n} color="success" style={{ fontSize: 11, margin: 0 }}>命中期望 Hop{n}</Tag>
                              ))}
                            </Space>
                            <Text type="secondary" style={{ fontSize: 12 }}>{docs.length} 条召回</Text>
                          </div>
                        }
                      >
                        {ah.query && (
                          <div style={{ fontSize: 12, color: '#555', marginBottom: 8, padding: '4px 8px', background: '#fafafa', borderRadius: 4 }}>
                            🔍 Query：{ah.query.length > 120 ? ah.query.slice(0, 120) + '...' : ah.query}
                          </div>
                        )}
                        {docs.length === 0
                          ? <Text type="secondary" style={{ fontSize: 12 }}>无召回结果</Text>
                          : docs.map((d: any, di: number) => {
                              const sim = d.cosine_distance_1 != null ? (1 - d.cosine_distance_1).toFixed(4) : null
                              const isExpected = hops.some((h: any) => h.file_id && h.file_id === d.file_id)
                              const matchedHops = hops
                                .map((h: any, hi: number) => h.file_id && h.file_id === d.file_id ? hi + 1 : null)
                                .filter(Boolean)
                              return (
                                <div key={di} style={{
                                  marginBottom: 6, padding: '5px 8px', borderRadius: 4,
                                  background: isExpected ? '#e6f7ff' : '#fafafa',
                                  border: `1px solid ${isExpected ? '#91d5ff' : '#f0f0f0'}`,
                                }}>
                                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <Space size={4}>
                                      <Text style={{ fontSize: 12, color: '#999' }}>#{di + 1}</Text>
                                      {matchedHops.map((n: any) => (
                                        <Tag key={n} color="blue" style={{ fontSize: 10, margin: 0, lineHeight: '16px' }}>Hop{n}</Tag>
                                      ))}
                                      <Text style={{ fontSize: 12 }}>{d.file_name || d.headers || d.file_id || '未知文件'}</Text>
                                    </Space>
                                    {sim && <Text type="secondary" style={{ fontSize: 11 }}>相似度 {sim}</Text>}
                                  </div>
                                  {d.paragraph_content && (
                                    <div style={{ fontSize: 11, color: '#666', marginTop: 3, maxHeight: 48, overflow: 'hidden', lineHeight: 1.4 }}>
                                      {d.paragraph_content.slice(0, 150)}
                                    </div>
                                  )}
                                </div>
                              )
                            })
                        }
                      </Card>
                    )
                  })}

                  {detailResult.error && (
                    <Card size="small" title="错误" style={{ marginBottom: 12 }}>
                      <Text type="danger">{detailResult.error}</Text>
                    </Card>
                  )}
                </div>
              )
            })()}
          </Drawer>
        </>
      )}
    </div>
  )
}
