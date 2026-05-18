import React, { useEffect, useState } from 'react'
import { Table, Button, Tabs, Tag, Statistic, Row, Col, Card, Drawer, Typography, Spin, Empty, Alert, Tooltip } from 'antd'
import { ArrowLeftOutlined, QuestionCircleOutlined } from '@ant-design/icons'
import { useParams, useNavigate } from 'react-router-dom'
import { Radar } from '@ant-design/charts'
import { reportApi, taskApi } from '../../services/api'
import { metricLabel, metricCn, METRICS } from '../../constants/metrics'

const { Text, Paragraph } = Typography

function MetricCard({ metricKey, value, color }: { metricKey: string; value: number | null; color: string }) {
  const metric = METRICS[metricKey]
  return (
    <Card size="small" style={{ textAlign: 'center' }}>
      <Statistic
        title={
          <div>
            <div style={{ fontWeight: 500 }}>{metricLabel(metricKey)}</div>
            {metric && (
              <div style={{ fontSize: 11, color: '#888', fontWeight: 400, marginTop: 2, lineHeight: 1.4 }}>
                {metric.desc}
              </div>
            )}
          </div>
        }
        value={value != null ? (value * 100).toFixed(1) : 'N/A'}
        suffix={value != null ? '%' : ''}
        valueStyle={{ color, fontSize: 22 }}
      />
    </Card>
  )
}

export default function Report() {
  const { taskId } = useParams<{ taskId: string }>()
  const navigate = useNavigate()
  const [report, setReport] = useState<any>(null)
  const [items, setItems] = useState<any[]>([])
  const [task, setTask] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [drawer, setDrawer] = useState<any>(null)

  useEffect(() => {
    Promise.all([
      reportApi.get(taskId!),
      reportApi.items(taskId!),
      taskApi.get(taskId!),
    ]).then(([r, i, t]: any[]) => {
      setReport(r.data)
      setItems(i.data?.records || [])
      setTask(t.data)
    }).finally(() => setLoading(false))
  }, [taskId])

  if (loading) return <Spin style={{ display: 'block', marginTop: 80 }} />
  if (!report) return <Empty description="报告不存在或任务尚未完成" style={{ marginTop: 80 }} />

  const selectedMetrics = task?.selected_metrics || []
  const shouldShow = (key: string) => selectedMetrics.length === 0 || selectedMetrics.includes(key)

  // Radar chart data - only show selected metrics
  const radarData = [
    { metric: metricCn('hit_rate'), value: report.avg_hit_rate ?? 0, key: 'hit_rate' },
    { metric: metricCn('mrr'), value: report.avg_mrr ?? 0, key: 'mrr' },
    { metric: metricCn('ndcg'), value: report.avg_ndcg ?? 0, key: 'ndcg' },
    { metric: metricCn('context_precision'), value: report.avg_context_precision ?? 0, key: 'context_precision' },
    { metric: metricCn('context_recall'), value: report.avg_context_recall ?? 0, key: 'context_recall' },
    { metric: metricCn('faithfulness'), value: report.avg_faithfulness ?? 0, key: 'faithfulness' },
    { metric: metricCn('answer_relevance'), value: report.avg_answer_relevance ?? 0, key: 'answer_relevance' },
    { metric: metricCn('answer_correctness'), value: report.avg_answer_correctness ?? 0, key: 'answer_correctness' },
    { metric: metricCn('groundedness'), value: report.avg_groundedness ?? 0, key: 'groundedness' },
  ].filter(d => d.value > 0 && shouldShow(d.key))

  const radarConfig = {
    data: radarData,
    xField: 'metric',
    yField: 'value',
    area: { style: { fillOpacity: 0.3 } },
    scale: { y: { domain: [0, 1] } },
    axis: { y: { tickCount: 5 } },
    height: 320,
  }

  const itemColumns = [
    { title: '问题', dataIndex: 'question', ellipsis: true, width: '25%' },
    shouldShow('hit_rate') && {
      title: metricCn('hit_rate'), dataIndex: 'hit_rate',
      render: (v: number | null) => v != null ? <Tag color={v >= 0.8 ? 'green' : v >= 0.5 ? 'orange' : 'red'}>{(v * 100).toFixed(0)}%</Tag> : '-',
    },
    shouldShow('mrr') && {
      title: metricCn('mrr'), dataIndex: 'mrr',
      render: (v: number | null) => v != null ? (v).toFixed(3) : '-',
    },
    shouldShow('ndcg') && {
      title: metricCn('ndcg'), dataIndex: 'ndcg',
      render: (v: number | null) => v != null ? (v).toFixed(3) : '-',
    },
    shouldShow('faithfulness') && {
      title: metricCn('faithfulness'), dataIndex: 'faithfulness',
      render: (v: number | null) => v != null
        ? <Tag color={v >= 0.8 ? 'green' : v >= 0.6 ? 'orange' : 'red'}>{(v * 100).toFixed(0)}%</Tag>
        : '-',
    },
    shouldShow('answer_relevance') && {
      title: metricCn('answer_relevance'), dataIndex: 'answer_relevance',
      render: (v: number | null) => v != null ? (v).toFixed(3) : '-',
    },
    {
      title: '状态', dataIndex: 'error',
      render: (v: string | null) => v ? <Tag color="red">失败</Tag> : <Tag color="green">正常</Tag>,
    },
    {
      title: '详情',
      render: (_: any, r: any) => (
        <Button size="small" onClick={() => setDrawer(r)}>查看</Button>
      ),
    },
  ].filter(Boolean)

  return (
    <div>
      <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate('/task')} style={{ paddingLeft: 0 }}>
        返回任务列表
      </Button>

      <h2 style={{ marginTop: 8 }}>
        评测报告 — {task?.name || taskId?.slice(0, 12)}
        <Tag color="success" style={{ marginLeft: 12, fontSize: 14 }}>
          {report.sample_count} 条样本
        </Tag>
      </h2>

      {/* Composite scores */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card style={{ background: '#f0f5ff', border: '1px solid #adc6ff' }}>
            <Statistic
              title="RAG Score（综合评分）"
              value={report.rag_score != null ? (report.rag_score * 100).toFixed(1) : 'N/A'}
              suffix={report.rag_score != null ? '%' : ''}
              valueStyle={{ color: '#1677ff', fontSize: 28 }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card style={{ background: '#fff7e6', border: '1px solid #ffd591' }}>
            <Statistic
              title="幻觉发生率"
              value={report.hallucination_rate != null ? (report.hallucination_rate * 100).toFixed(1) : 'N/A'}
              suffix={report.hallucination_rate != null ? '%' : ''}
              valueStyle={{ color: report.hallucination_rate > 0.2 ? '#cf1322' : '#389e0d', fontSize: 28 }}
            />
          </Card>
        </Col>
      </Row>

      {/* Interpretation */}
      {report.interpretation && (
        <Alert
          message="评测结果解读"
          description={
            <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.8 }}>
              {report.interpretation}
            </div>
          }
          type="info"
          showIcon
          style={{ marginBottom: 24 }}
        />
      )}

      <Tabs
        items={[
          {
            key: 'overview',
            label: '指标总览',
            children: (
              <Row gutter={[16, 16]}>
                <Col span={12}>
                  <Card title="雷达图" size="small">
                    {radarData.length > 0 ? <Radar {...radarConfig} /> : <Empty description="暂无数据" />}
                  </Card>
                </Col>
                <Col span={12}>
                  <Row gutter={[12, 12]}>
                    {shouldShow('hit_rate') && <Col span={12}><MetricCard metricKey="hit_rate" value={report.avg_hit_rate} color="#1677ff" /></Col>}
                    {shouldShow('mrr') && <Col span={12}><MetricCard metricKey="mrr" value={report.avg_mrr} color="#1677ff" /></Col>}
                    {shouldShow('ndcg') && <Col span={12}><MetricCard metricKey="ndcg" value={report.avg_ndcg} color="#1677ff" /></Col>}
                    {shouldShow('context_precision') && <Col span={12}><MetricCard metricKey="context_precision" value={report.avg_context_precision} color="#722ed1" /></Col>}
                    {shouldShow('context_recall') && <Col span={12}><MetricCard metricKey="context_recall" value={report.avg_context_recall} color="#722ed1" /></Col>}
                    {shouldShow('faithfulness') && <Col span={12}><MetricCard metricKey="faithfulness" value={report.avg_faithfulness} color="#52c41a" /></Col>}
                    {shouldShow('answer_relevance') && <Col span={12}><MetricCard metricKey="answer_relevance" value={report.avg_answer_relevance} color="#52c41a" /></Col>}
                    {shouldShow('answer_correctness') && <Col span={12}><MetricCard metricKey="answer_correctness" value={report.avg_answer_correctness} color="#52c41a" /></Col>}
                    {shouldShow('groundedness') && <Col span={12}><MetricCard metricKey="groundedness" value={report.avg_groundedness} color="#fa8c16" /></Col>}
                  </Row>
                </Col>
              </Row>
            ),
          },
          {
            key: 'items',
            label: `样本明细 (${items.length})`,
            children: (
              <Table
                rowKey="id"
                dataSource={items}
                columns={itemColumns}
                size="small"
                scroll={{ x: 900 }}
                rowClassName={(r) => r.error ? 'ant-table-row-error' : ''}
              />
            ),
          },
        ]}
      />

      {/* Sample detail drawer */}
      <Drawer
        title="样本详情"
        open={!!drawer}
        onClose={() => setDrawer(null)}
        width={640}
      >
        {drawer && (
          <div>
            <Paragraph><Text strong>问题：</Text>{drawer.question}</Paragraph>
            <Paragraph><Text strong>参考答案：</Text>{drawer.reference_answer}</Paragraph>
            <Paragraph><Text strong>Agent 回答：</Text>{drawer.agent_answer || '-'}</Paragraph>

            {(shouldShow('hit_rate') || shouldShow('mrr') || shouldShow('ndcg') || shouldShow('context_precision') || shouldShow('context_recall')) && (
              <Card title="检索指标" size="small" style={{ marginBottom: 12 }}>
                <Row gutter={16}>
                  {[
                    shouldShow('hit_rate') && [metricLabel('hit_rate'), drawer.hit_rate],
                    shouldShow('mrr') && [metricLabel('mrr'), drawer.mrr],
                    shouldShow('ndcg') && [metricLabel('ndcg'), drawer.ndcg],
                    shouldShow('context_precision') && [metricLabel('context_precision'), drawer.context_precision],
                    shouldShow('context_recall') && [metricLabel('context_recall'), drawer.context_recall],
                  ].filter(Boolean).map(([k, v]) => (
                    <Col span={8} key={k as string}>
                      <Statistic title={k as string} value={v != null ? (v as number).toFixed(3) : 'N/A'} />
                    </Col>
                  ))}
                </Row>
              </Card>
            )}

            {(shouldShow('faithfulness') || shouldShow('answer_relevance') || shouldShow('answer_correctness') || shouldShow('groundedness')) && (
              <Card title="生成指标" size="small" style={{ marginBottom: 12 }}>
                <Row gutter={16}>
                  {[
                    shouldShow('faithfulness') && [metricLabel('faithfulness'), drawer.faithfulness],
                    shouldShow('answer_relevance') && [metricLabel('answer_relevance'), drawer.answer_relevance],
                    shouldShow('answer_correctness') && [metricLabel('answer_correctness'), drawer.answer_correctness],
                    shouldShow('groundedness') && [metricLabel('groundedness'), drawer.groundedness],
                  ].filter(Boolean).map(([k, v]) => (
                    <Col span={6} key={k as string}>
                      <Statistic title={k as string} value={v != null ? (v as number).toFixed(3) : 'N/A'} />
                    </Col>
                  ))}
                </Row>
              </Card>
            )}

            {drawer.judge_detail && Object.keys(drawer.judge_detail).length > 0 && (
              <Card title="Judge 推理过程" size="small">
                <pre style={{ fontSize: 12, maxHeight: 300, overflow: 'auto', background: '#f5f5f5', padding: 8 }}>
                  {JSON.stringify(drawer.judge_detail, null, 2)}
                </pre>
              </Card>
            )}

            {drawer.error && (
              <Card title="错误信息" size="small" style={{ borderColor: '#ff4d4f' }}>
                <Text type="danger">{drawer.error}</Text>
              </Card>
            )}
          </div>
        )}
      </Drawer>
    </div>
  )
}
