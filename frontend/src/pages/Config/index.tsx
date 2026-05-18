import React, { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Select, Popconfirm, message, Tag, Space } from 'antd'
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import { configApi } from '../../services/api'

const { Option } = Select

export default function Config() {
  const [platforms, setPlatforms] = useState<any[]>([])
  const [judges, setJudges] = useState<any[]>([])
  const [platformModal, setPlatformModal] = useState(false)
  const [judgeModal, setJudgeModal] = useState(false)
  const [form] = Form.useForm()
  const [judgeForm] = Form.useForm()
  const [selectedPlatformKeys, setSelectedPlatformKeys] = useState<React.Key[]>([])
  const [selectedJudgeKeys, setSelectedJudgeKeys] = useState<React.Key[]>([])

  const load = async () => {
    const [p, j] = await Promise.all([configApi.listPlatforms(), configApi.listJudges()])
    setPlatforms((p as any).data || [])
    setJudges((j as any).data || [])
  }

  useEffect(() => { load() }, [])

  const savePlatform = async () => {
    const vals = await form.validateFields()
    await configApi.createPlatform(vals)
    message.success('平台配置已保存')
    setPlatformModal(false)
    form.resetFields()
    load()
  }

  const saveJudge = async () => {
    const vals = await judgeForm.validateFields()
    await configApi.createJudge(vals)
    message.success('Judge 配置已保存')
    setJudgeModal(false)
    judgeForm.resetFields()
    load()
  }

  // ── 批量删除平台配置 ───────────────────────────────────────────────────────────
  const handleBatchDeletePlatform = async () => {
    if (selectedPlatformKeys.length === 0) {
      message.warning('请先选择要删除的平台配置')
      return
    }
    Modal.confirm({
      title: `确认删除选中的 ${selectedPlatformKeys.length} 个平台配置？`,
      content: '删除后将无法恢复。',
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      async onOk() {
        try {
          await Promise.all(selectedPlatformKeys.map(id => configApi.deletePlatform(id as string)))
          message.success(`成功删除 ${selectedPlatformKeys.length} 个平台配置`)
          setSelectedPlatformKeys([])
          load()
        } catch (e: any) {
          message.error(e?.message || '批量删除失败')
        }
      },
    })
  }

  // ── 批量删除 Judge 配置 ───────────────────────────────────────────────────────
  const handleBatchDeleteJudge = async () => {
    if (selectedJudgeKeys.length === 0) {
      message.warning('请先选择要删除的 Judge 配置')
      return
    }
    Modal.confirm({
      title: `确认删除选中的 ${selectedJudgeKeys.length} 个 Judge 配置？`,
      content: '删除后将无法恢复。',
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      async onOk() {
        try {
          await Promise.all(selectedJudgeKeys.map(id => configApi.deleteJudge(id as string)))
          message.success(`成功删除 ${selectedJudgeKeys.length} 个 Judge 配置`)
          setSelectedJudgeKeys([])
          load()
        } catch (e: any) {
          message.error(e?.message || '批量删除失败')
        }
      },
    })
  }

  const platformCols = [
    { title: '名称', dataIndex: 'name' },
    { title: '类型', dataIndex: 'type', render: (v: string) => <Tag color="blue">{v}</Tag> },
    { title: 'Base URL', dataIndex: 'base_url' },
    { title: 'Org ID', dataIndex: 'org_id' },
    { title: '创建时间', dataIndex: 'created_at', render: (v: string) => v?.slice(0, 19) },
    {
      title: '操作', render: (_: any, r: any) => (
        <Popconfirm title="确认删除？" onConfirm={() => configApi.deletePlatform(r.id).then(load)}>
          <Button danger size="small" icon={<DeleteOutlined />} />
        </Popconfirm>
      )
    },
  ]

  const judgeCols = [
    { title: '名称', dataIndex: 'name' },
    { title: '模型', dataIndex: 'model', render: (v: string) => <Tag color="purple">{v}</Tag> },
    { title: 'Base URL', dataIndex: 'base_url' },
    { title: 'Embed 模型', dataIndex: 'embed_model', render: (v: string) => v ? <Tag color="cyan">{v}</Tag> : '-' },
    { title: '创建时间', dataIndex: 'created_at', render: (v: string) => v?.slice(0, 19) },
    {
      title: '操作', render: (_: any, r: any) => (
        <Popconfirm title="确认删除？" onConfirm={() => configApi.deleteJudge(r.id).then(load)}>
          <Button danger size="small" icon={<DeleteOutlined />} />
        </Popconfirm>
      )
    },
  ]

  return (
    <div>
      <h2>配置管理</h2>

      <div style={{ marginBottom: 32 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>平台连接配置</h3>
          <Space>
            {selectedPlatformKeys.length > 0 && (
              <Button danger icon={<DeleteOutlined />} onClick={handleBatchDeletePlatform}>
                批量删除 ({selectedPlatformKeys.length})
              </Button>
            )}
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setPlatformModal(true)}>新增平台</Button>
          </Space>
        </div>
        <Table
          rowKey="id"
          dataSource={platforms}
          columns={platformCols}
          pagination={false}
          size="small"
          rowSelection={{
            selectedRowKeys: selectedPlatformKeys,
            onChange: setSelectedPlatformKeys,
          }}
        />
      </div>

      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>Judge 模型配置</h3>
          <Space>
            {selectedJudgeKeys.length > 0 && (
              <Button danger icon={<DeleteOutlined />} onClick={handleBatchDeleteJudge}>
                批量删除 ({selectedJudgeKeys.length})
              </Button>
            )}
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setJudgeModal(true)}>新增 Judge</Button>
          </Space>
        </div>
        <Table
          rowKey="id"
          dataSource={judges}
          columns={judgeCols}
          pagination={false}
          size="small"
          rowSelection={{
            selectedRowKeys: selectedJudgeKeys,
            onChange: setSelectedJudgeKeys,
          }}
        />
      </div>

      <Modal title="新增平台配置" open={platformModal} onOk={savePlatform} onCancel={() => setPlatformModal(false)}>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="type" label="类型" initialValue="dagent">
            <Select><Option value="dagent">dagent</Option><Option value="custom">custom</Option></Select>
          </Form.Item>
          <Form.Item name="base_url" label="Base URL" rules={[{ required: true }]}><Input placeholder="http://localhost:8000" /></Form.Item>
          <Form.Item name="org_id" label="Org ID" rules={[{ required: true }]}><Input placeholder="a4d49699ba313815..." /></Form.Item>
          <Form.Item name="token" label="Token"><Input.Password /></Form.Item>
        </Form>
      </Modal>

      <Modal title="新增 Judge 配置" open={judgeModal} onOk={saveJudge} onCancel={() => setJudgeModal(false)} width={560}>
        <Form form={judgeForm} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="base_url" label="Base URL (OpenAI 兼容)" rules={[{ required: true }]}><Input placeholder="https://api.openai.com/v1" /></Form.Item>
          <Form.Item name="api_key" label="API Key" rules={[{ required: true }]}><Input.Password /></Form.Item>
          <Form.Item name="model" label="模型" rules={[{ required: true }]}><Input placeholder="gpt-4o" /></Form.Item>
          <Form.Item name="embed_base_url" label="Embedding Base URL（可选，不填则复用上方 Base URL）"><Input placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1" /></Form.Item>
          <Form.Item name="embed_api_key" label="Embedding API Key（可选，不填则复用上方 Key）"><Input.Password /></Form.Item>
          <Form.Item name="embed_model" label="Embedding 模型" initialValue="text-embedding-3-small"><Input placeholder="text-embedding-v2" /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
