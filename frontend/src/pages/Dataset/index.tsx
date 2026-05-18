import React, { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Upload, Popconfirm, message, Tag, Space, Tooltip } from 'antd'
import { PlusOutlined, UploadOutlined, DeleteOutlined, EyeOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { datasetApi } from '../../services/api'

export default function Dataset() {
  const [datasets, setDatasets] = useState<any[]>([])
  const [createModal, setCreateModal] = useState(false)
  const [form] = Form.useForm()
  const navigate = useNavigate()
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])

  const load = async () => {
    const res = await datasetApi.list() as any
    setDatasets(res.data || [])
  }

  useEffect(() => { load() }, [])

  const create = async () => {
    const vals = await form.validateFields()
    await datasetApi.create(vals)
    message.success('数据集已创建')
    setCreateModal(false)
    form.resetFields()
    load()
  }

  const handleImport = async (file: File) => {
    try {
      await datasetApi.import(file)
      message.success('导入成功')
      load()
    } catch {
      message.error('导入失败')
    }
    return false
  }

  // ── 批量删除 ────────────────────────────────────────────────────────────────
  const handleBatchDelete = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要删除的数据集')
      return
    }
    Modal.confirm({
      title: `确认删除选中的 ${selectedRowKeys.length} 个数据集？`,
      content: '删除后将无法恢复，相关样本也会被删除。',
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      async onOk() {
        try {
          await Promise.all(selectedRowKeys.map(id => datasetApi.delete(id as string)))
          message.success(`成功删除 ${selectedRowKeys.length} 个数据集`)
          setSelectedRowKeys([])
          load()
        } catch (e: any) {
          message.error(e?.message || '批量删除失败')
        }
      },
    })
  }

  const columns = [
    { title: '名称', dataIndex: 'name', render: (v: string, r: any) => (
      <a onClick={() => navigate(`/dataset/${r.id}`)}>{v}</a>
    )},
    { title: '描述', dataIndex: 'description', ellipsis: true },
    { title: '样本数', dataIndex: 'sample_count', render: (v: number) => <Tag color="blue">{v}</Tag> },
    { title: '创建时间', dataIndex: 'created_at', render: (v: string) => v?.slice(0, 19) },
    {
      title: '操作',
      render: (_: any, r: any) => (
        <Space>
          <Tooltip title="查看样本">
            <Button size="small" icon={<EyeOutlined />} onClick={() => navigate(`/dataset/${r.id}`)} />
          </Tooltip>
          <Popconfirm title="确认删除该数据集及所有样本？" onConfirm={() => datasetApi.delete(r.id).then(load)}>
            <Button danger size="small" icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>测试集管理</h2>
        <Space>
          {selectedRowKeys.length > 0 && (
            <Button danger icon={<DeleteOutlined />} onClick={handleBatchDelete}>
              批量删除 ({selectedRowKeys.length})
            </Button>
          )}
          <Upload beforeUpload={handleImport} showUploadList={false} accept=".json">
            <Button icon={<UploadOutlined />}>导入 JSON</Button>
          </Upload>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModal(true)}>新建数据集</Button>
        </Space>
      </div>

      <Table
        rowKey="id"
        dataSource={datasets}
        columns={columns}
        rowSelection={{
          selectedRowKeys,
          onChange: setSelectedRowKeys,
        }}
      />

      <Modal title="新建数据集" open={createModal} onOk={create} onCancel={() => setCreateModal(false)}>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={3} /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
