import http from './http'

export const configApi = {
  listPlatforms: () => http.get('/config/platform'),
  createPlatform: (data: any) => http.post('/config/platform', data),
  deletePlatform: (id: string) => http.delete(`/config/platform/${id}`),
  listJudges: () => http.get('/config/judge'),
  createJudge: (data: any) => http.post('/config/judge', data),
  deleteJudge: (id: string) => http.delete(`/config/judge/${id}`),
}

export const datasetApi = {
  list: () => http.get('/dataset/list'),
  get: (id: string) => http.get(`/dataset/${id}`),
  create: (data: any) => http.post('/dataset/create', data),
  delete: (id: string) => http.delete(`/dataset/${id}`),
  addSample: (data: any) => http.post('/dataset/sample/add', data),
  generate: (data: any) => http.post('/dataset/generate', data),
  getGenerateProgress: (genTaskId: string) => http.get(`/dataset/generate/${genTaskId}`),
  chunksPreview: (platformConfigId: string, knowledgeHubId: string) =>
    http.get(`/dataset/chunks-preview?platform_config_id=${platformConfigId}&knowledge_hub_id=${knowledgeHubId}`),
  import: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return http.post('/dataset/import', form)
  },
}

export const taskApi = {
  list: () => http.get('/task/list'),
  get: (id: string) => http.get(`/task/${id}`),
  run: (data: any) => http.post('/task/run', data),
  delete: (id: string) => http.delete(`/task/${id}`),
}

export const reportApi = {
  get: (taskId: string) => http.get(`/report/${taskId}`),
  items: (taskId: string) => http.get(`/report/${taskId}/items`),
}

export const singleJumpApi = {
  createTask: (formData: FormData) => http.post('/single-jump/task', formData),
  createTaskBatch: (formData: FormData) => http.post('/single-jump/task/batch', formData),
  listTasks: () => http.get('/single-jump/task/list'),
  getTask: (id: string) => http.get(`/single-jump/task/${id}`),
  deleteTask: (id: string) => http.delete(`/single-jump/task/${id}`),
  getSummary: (id: string) => http.get(`/single-jump/task/${id}/summary`),
  getSections: (id: string) => http.get(`/single-jump/task/${id}/sections`),
  getResults: (id: string, section?: string) =>
    http.get(`/single-jump/task/${id}/results${section ? `?section=${encodeURIComponent(section)}` : ''}`),
  getAgentRecall: (taskId: string, resultId: string, agentId: string) =>
    http.get(`/single-jump/task/${taskId}/agent-recall?result_id=${encodeURIComponent(resultId)}&agent_id=${encodeURIComponent(agentId)}`),
  listAgents: (taskId: string) => http.get(`/single-jump/task/${taskId}/agents`),
  exportFailedMd: (taskId: string) => `/api/single-jump/task/${taskId}/export-failed-md`,
  exportFileMissMd: (taskId: string) => `/api/single-jump/task/${taskId}/export-file-miss-md`,
}

export const qaGenApi = {
  createTask: (formData: FormData) => http.post('/qa-gen/task', formData),
  createTaskFromDagent: (formData: FormData) => http.post('/qa-gen/task/from-dagent', formData),
  getDagentStats: (orgId: string, envUrl?: string) => http.get(`/qa-gen/dagent/stats?org_id=${encodeURIComponent(orgId)}${envUrl ? `&env_url=${encodeURIComponent(envUrl)}` : ''}`),
  listDagentFiles: (orgId: string, envUrl?: string) => http.get(`/qa-gen/dagent/files?org_id=${encodeURIComponent(orgId)}${envUrl ? `&env_url=${encodeURIComponent(envUrl)}` : ''}`),
  getDagentTree: (orgId: string, envUrl?: string) => http.get(`/qa-gen/dagent/tree?org_id=${encodeURIComponent(orgId)}${envUrl ? `&env_url=${encodeURIComponent(envUrl)}` : ''}`),
  listTasks: () => http.get('/qa-gen/task/list'),
  getTask: (id: string) => http.get(`/qa-gen/task/${id}`),
  deleteTask: (id: string) => http.delete(`/qa-gen/task/${id}`),
  listQuestions: (taskId: string, params?: { status?: string; section?: string; page?: number; page_size?: number }) => {
    const q = new URLSearchParams()
    if (params?.status) q.set('status', params.status)
    if (params?.section) q.set('section', params.section)
    if (params?.page) q.set('page', String(params.page))
    if (params?.page_size) q.set('page_size', String(params.page_size))
    const qs = q.toString()
    return http.get(`/qa-gen/task/${taskId}/questions${qs ? `?${qs}` : ''}`)
  },
  listSections: (taskId: string) => http.get(`/qa-gen/task/${taskId}/sections`),
  approveQuestion: (id: string) => http.post(`/qa-gen/question/${id}/approve`),
  rejectQuestion: (id: string) => http.post(`/qa-gen/question/${id}/reject`),
  editQuestion: (id: string, data: { question?: string; reference_answer?: string }) =>
    http.put(`/qa-gen/question/${id}`, data),
  batchApprove: (taskId: string, minQuality = 0) =>
    http.post(`/qa-gen/task/${taskId}/batch-approve?min_quality=${minQuality}`),
  exportMd: (taskId: string) => `/api/qa-gen/task/${taskId}/export-md`,
  createDataset: (taskId: string, data: { name: string; knowledge_hub_id?: string; description?: string }) =>
    http.post(`/qa-gen/task/${taskId}/create-dataset`, data),
}

export const loopApi = {
  createTask: (formData: FormData) => http.post('/loop/task', formData),
  listTasks: () => http.get('/loop/task/list'),
  getTask: (id: string) => http.get(`/loop/task/${id}`),
  pauseTask: (id: string) => http.post(`/loop/task/${id}/pause`),
  resumeTask: (id: string) => http.post(`/loop/task/${id}/resume`),
  stopTask: (id: string) => http.post(`/loop/task/${id}/stop`),
  deleteTask: (id: string) => http.delete(`/loop/task/${id}`),
  getRounds: (id: string) => http.get(`/loop/task/${id}/rounds`),
  getQuestions: (id: string, params?: { status?: string; category?: string; page?: number; page_size?: number }) => {
    const q = new URLSearchParams()
    if (params?.status) q.set('status', params.status)
    if (params?.category) q.set('category', params.category)
    if (params?.page) q.set('page', String(params.page))
    if (params?.page_size) q.set('page_size', String(params.page_size))
    const qs = q.toString()
    return http.get(`/loop/task/${id}/questions${qs ? `?${qs}` : ''}`)
  },
  export: (id: string, category: string, format: 'md' | 'json' = 'md') =>
    `/api/loop/task/${id}/export?category=${category}&format=${format}`,
}

export const multiHopApi = {
  createTask: (formData: FormData) => http.post('/multi-hop/task', formData),
  listTasks: () => http.get('/multi-hop/task/list'),
  getTask: (id: string) => http.get(`/multi-hop/task/${id}`),
  deleteTask: (id: string) => http.delete(`/multi-hop/task/${id}`),
  getResults: (id: string) => http.get(`/multi-hop/task/${id}/results`),
  getSummary: (id: string) => http.get(`/multi-hop/task/${id}/summary`),
  listDagentAgents: (envUrl: string, orgId: string, dUserId = 'test') =>
    http.get(`/multi-hop/dagent/agents?env_url=${encodeURIComponent(envUrl)}&org_id=${encodeURIComponent(orgId)}&d_user_id=${dUserId}`),
}

export const promptTemplateApi = {
  list: () => http.get('/prompt-template/list'),
  getDefault: () => http.get('/prompt-template/default'),
  create: (data: { name: string; description?: string; content: string }) =>
    http.post('/prompt-template', data),
  update: (id: string, data: { name: string; description?: string; content: string }) =>
    http.put(`/prompt-template/${id}`, data),
  delete: (id: string) => http.delete(`/prompt-template/${id}`),
}

export const multiHopGenApi = {
  createTask: (formData: FormData) => http.post('/multi-hop-gen/task', formData),
  createTaskFromDagent: (formData: FormData) => http.post('/multi-hop-gen/task/from-dagent', formData),
  getDagentStats: (orgId: string, envUrl?: string) => http.get(`/multi-hop-gen/dagent/stats?org_id=${encodeURIComponent(orgId)}${envUrl ? `&env_url=${encodeURIComponent(envUrl)}` : ''}`),
  listDagentFiles: (orgId: string, envUrl?: string) => http.get(`/multi-hop-gen/dagent/files?org_id=${encodeURIComponent(orgId)}${envUrl ? `&env_url=${encodeURIComponent(envUrl)}` : ''}`),
  listTasks: () => http.get('/multi-hop-gen/task/list'),
  getTask: (id: string) => http.get(`/multi-hop-gen/task/${id}`),
  deleteTask: (id: string) => http.delete(`/multi-hop-gen/task/${id}`),
  listQuestions: (taskId: string, params?: { status?: string; page?: number; page_size?: number }) => {
    const q = new URLSearchParams()
    if (params?.status) q.set('status', params.status)
    if (params?.page) q.set('page', String(params.page))
    if (params?.page_size) q.set('page_size', String(params.page_size))
    const qs = q.toString()
    return http.get(`/multi-hop-gen/task/${taskId}/questions${qs ? `?${qs}` : ''}`)
  },
  approveQuestion: (id: string) => http.post(`/multi-hop-gen/question/${id}/approve`),
  rejectQuestion: (id: string) => http.post(`/multi-hop-gen/question/${id}/reject`),
  editQuestion: (id: string, data: { question?: string; answer?: string; type?: string }) =>
    http.put(`/multi-hop-gen/question/${id}`, data),
  batchApprove: (taskId: string, minQuality = 0) =>
    http.post(`/multi-hop-gen/task/${taskId}/batch-approve?min_quality=${minQuality}`),
  exportMd: (taskId: string) => `/api/multi-hop-gen/task/${taskId}/export-md`,
  createTest: (taskId: string, data: { env_url: string; org_id: string; agent_id: string; llm_type?: string; d_user_id?: string; top_k?: number; concurrency?: number; name?: string }) =>
    http.post(`/multi-hop-gen/task/${taskId}/create-test`, data),
}

