import React, { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Select, InputNumber, Tag, Space, Popconfirm, message, Checkbox, Tooltip, Divider } from 'antd'
import { PlusOutlined, DeleteOutlined, EyeOutlined, ReloadOutlined, QuestionCircleOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { taskApi, datasetApi, configApi } from '../../services/api'
import { METRICS, RETRIEVAL_METRICS, GENERATION_METRICS, ALL_METRIC_KEYS } from '../../constants/metrics'

const { Option } = Select

const STATUS_COLOR: Record<string, string> = {
  pending: 'default',
  running: 'processing',
  done: 'success',
  failed: 'error',
}

export default function Task() {
  const [tasks, setTasks] = useState<any[]>([])
  const [datasets, setDatasets] = useState<any[]>([])
  const [platforms, setPlatforms] = useState<any[]>([])
  const [judges, setJudges] = useState<any[]>([])
  const [modal, setModal] = useState(false)
  const [form] = Form.useForm()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])

  const load = async () => {
    const res = await taskApi.list() as any
    setTasks(res.data || [])
  }

  useEffect(() => {
    load()
    datasetApi.list().then((r: any) => {
      const ds = r.data || []
      setDatasets(ds)
      const datasetId = searchParams.get('dataset_id')
      if (datasetId) {
        // 检查数据集是否存在
        const found = ds.find((d: any) => d.id === datasetId)
        if (found) {
          form.setFieldsValue({ dataset_id: datasetId })
          // 自动打开新建任务模态框
          setModal(true)
        }
      }
    })
    configApi.listPlatforms().then((r: any) => setPlatforms(r.data || []))
    configApi.listJudges().then((r: any) => setJudges(r.data || []))
  }, [])

  const runTask = async () => {
    const vals = await form.validateFields()
    await taskApi.run(vals)
    message.success('评测任务已启动')
    setModal(false)
    form.resetFields()
    load()
  }

  // ── 批量删除 ────────────────────────────────────────────────────────────────
  const handleBatchDelete = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要删除的任务')
      return
    }
    Modal.confirm({
      title: `确认删除选中的 ${selectedRowKeys.length} 个评测任务？`,
      content: '删除后将无法恢复，相关评测结果也会被删除。',
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      async onOk() {
        try {
          await Promise.all(selectedRowKeys.map(id => taskApi.delete(id as string)))
          message.success(`成功删除 ${selectedRowKeys.length} 个任务`)
          setSelectedRowKeys([])
          load()
        } catch (e: any) {
          message.error(e?.message || '批量删除失败')
        }
      },
    })
  }

  const columns = [
    {
      title: '任务名称', dataIndex: 'name',
      render: (v: string, r: any) => v || r.id.slice(0, 8) + '...',
    },
    { title: '数据集', dataIndex: 'dataset_id', ellipsis: true },
    {
      title: '评测指标',
      render: (_: any, r: any) => {
        const metrics = r.selected_metrics || []
        if (metrics.length === 0) {
          // 向后兼容：显示检索/生成标签
          const tags = []
          if (r.eval_retrieval) tags.push(<Tag key="r" color="blue">检索</Tag>)
          if (r.eval_generation) tags.push(<Tag key="g" color="purple">生成</Tag>)
          return <>{tags}</>
        }
        return <Tag>{metrics.length} 项指标</Tag>
      },
    },
    {
      title: '状态', dataIndex: 'status',
      render: (v: string) => <Tag color={STATUS_COLOR[v] || 'default'}>{v}</Tag>,
    },
    {
      title: '进度', render: (_: any, r: any) =>
        r.total > 0 ? `${r.progress} / ${r.total}` : '-',
    },
    { title: '创建时间', dataIndex: 'created_at', render: (v: string) => v?.slice(0, 19) },
    {
      title: '操作',
      render: (_: any, r: any) => (
        <Space>
          {r.status === 'done' && (
            <Button size="small" icon={<EyeOutlined />} onClick={() => navigate(`/report/${r.id}`)}>
              报告
            </Button>
          )}
          <Popconfirm title="确认删除该任务及结果？" onConfirm={() => taskApi.delete(r.id).then(load)}>
            <Button danger size="small" icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>评测任务</h2>
        <Space>
          {selectedRowKeys.length > 0 && (
            <Button danger icon={<DeleteOutlined />} onClick={handleBatchDelete}>
              批量删除 ({selectedRowKeys.length})
            </Button>
          )}
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setModal(true)}>新建任务</Button>
        </Space>
      </div>

      <Table
        rowKey="id"
        dataSource={tasks}
        columns={columns}
        rowSelection={{
          selectedRowKeys,
          onChange: setSelectedRowKeys,
        }}
      />

      <Modal title="新建评测任务" open={modal} onOk={runTask} onCancel={() => setModal(false)} width={700}>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="任务名称（可选）"><Input /></Form.Item>
          <Form.Item name="dataset_id" label="测试集" rules={[{ required: true }]}>
            <Select placeholder="选择测试集">
              {datasets.map((d: any) => (
                <Option key={d.id} value={d.id}>{d.name} ({d.sample_count} 条)</Option>
              ))}
            </Select>
          </Form.Item>
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
          <Form.Item name="agent_id" label="Agent ID" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="knowledge_hub_id" label="知识库 ID" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="top_k" label="Top K" initialValue={10}>
            <InputNumber min={1} max={50} />
          </Form.Item>

          <Divider orientation="left">评测指标选择</Divider>
          <Form.Item name="selected_metrics" label="选择要评测的指标" initialValue={ALL_METRIC_KEYS}>
            <Checkbox.Group style={{ width: '100%' }}>
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontWeight: 'bold', marginBottom: 8, color: '#1677ff' }}>检索层指标</div>
                <Space direction="vertical" size={4}>
                  {RETRIEVAL_METRICS.map(m => (
                    <Checkbox key={m.key} value={m.key}>
                      <span style={{ fontWeight: 500 }}>{m.cn} ({m.en})</span>
                      <span style={{ marginLeft: 8, fontSize: 12, color: '#888' }}>{m.desc}</span>
                    </Checkbox>
                  ))}
                </Space>
              </div>
              <div>
                <div style={{ fontWeight: 'bold', marginBottom: 8, color: '#722ed1' }}>生成层指标</div>
                <Space direction="vertical" size={4}>
                  {GENERATION_METRICS.map(m => (
                    <Checkbox key={m.key} value={m.key}>
                      <span style={{ fontWeight: 500 }}>{m.cn} ({m.en})</span>
                      <span style={{ marginLeft: 8, fontSize: 12, color: '#888' }}>{m.desc}</span>
                    </Checkbox>
                  ))}
                </Space>
              </div>
            </Checkbox.Group>
          </Form.Item>

          <Form.Item name="concurrency" label="并发数" initialValue={3}>
            <InputNumber min={1} max={10} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
