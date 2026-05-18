export interface MetricMeta {
  key: string
  en: string
  cn: string
  group: 'retrieval' | 'generation'
  desc: string
}

export const METRICS: Record<string, MetricMeta> = {
  hit_rate:           { key: 'hit_rate',           en: 'Hit Rate@K',        cn: '命中率',         group: 'retrieval',   desc: '检索结果中包含相关文档的比例' },
  mrr:                { key: 'mrr',                en: 'MRR@K',             cn: '平均倒数排名',   group: 'retrieval',   desc: '第一个相关文档排名位置的倒数均值' },
  ndcg:               { key: 'ndcg',               en: 'NDCG@K',            cn: '归一化折损累积增益', group: 'retrieval', desc: '考虑排名位置的检索质量综合评分' },
  context_precision:  { key: 'context_precision',  en: 'Context Precision', cn: '上下文精确度',   group: 'retrieval',   desc: '检索到的文档中与问题相关的比例' },
  context_recall:     { key: 'context_recall',     en: 'Context Recall',    cn: '上下文召回率',   group: 'retrieval',   desc: '参考答案中的信息被检索文档覆盖的比例' },
  faithfulness:       { key: 'faithfulness',       en: 'Faithfulness',      cn: '忠实度',         group: 'generation',  desc: '回答内容是否忠实于检索到的上下文' },
  answer_relevance:   { key: 'answer_relevance',   en: 'Answer Relevance',  cn: '回答相关性',     group: 'generation',  desc: '回答与原始问题的相关程度' },
  answer_correctness: { key: 'answer_correctness', en: 'Answer Correctness',cn: '回答正确性',     group: 'generation',  desc: '回答与参考答案的事实一致程度' },
  groundedness:       { key: 'groundedness',       en: 'Groundedness',      cn: '可溯源性',       group: 'generation',  desc: '回答中的声明能否追溯到检索文档' },
}

export const RETRIEVAL_METRICS = Object.values(METRICS).filter(m => m.group === 'retrieval')
export const GENERATION_METRICS = Object.values(METRICS).filter(m => m.group === 'generation')
export const ALL_METRIC_KEYS = Object.keys(METRICS)

/** 根据 key 获取中文显示名 */
export function metricLabel(key: string): string {
  const m = METRICS[key]
  return m ? `${m.cn} (${m.en})` : key
}

/** 根据 key 获取短中文名 */
export function metricCn(key: string): string {
  return METRICS[key]?.cn ?? key
}
