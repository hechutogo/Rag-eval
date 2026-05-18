import React from 'react'
import { BrowserRouter, Routes, Route, NavLink, Navigate, useLocation } from 'react-router-dom'
import { Layout, Menu } from 'antd'
import {
  DatabaseOutlined,
  PlayCircleOutlined,
  BarChartOutlined,
  SettingOutlined,
  AimOutlined,
  BulbOutlined,
  ForkOutlined,
} from '@ant-design/icons'
import Dataset from './pages/Dataset'
import DatasetDetail from './pages/Dataset/detail'
import Task from './pages/Task'
import Report from './pages/Report'
import Config from './pages/Config'
import SingleJump from './pages/SingleJump'
import QaGen from './pages/QaGen'
import MultiHop from './pages/MultiHop'

const { Sider, Content } = Layout

const NAV = [
  { key: '/dataset',     icon: <DatabaseOutlined />,    label: '测试集' },
  { key: '/task',        icon: <PlayCircleOutlined />,   label: '评测任务' },
  { key: '/single-jump', icon: <AimOutlined />,          label: '单跳召回测试' },
  { key: '/multi-hop',   icon: <ForkOutlined />,         label: '多跳召回测试' },
  { key: '/qa-gen',      icon: <BulbOutlined />,         label: '问题生成' },
  { key: '/config',      icon: <SettingOutlined />,      label: '配置管理' },
]

function AppLayout() {
  const location = useLocation()
  const currentPath = location.pathname.split('/').slice(0, 2).join('/')

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider theme="dark" width={200}>
        <div style={{ color: '#fff', fontWeight: 700, fontSize: 16, padding: '20px 24px 12px' }}>
          RAG Eval
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[currentPath]}
          items={NAV.map(n => ({
            key: n.key,
            icon: n.icon,
            label: <NavLink to={n.key}>{n.label}</NavLink>,
          }))}
        />
      </Sider>
      <Layout>
        <Content style={{ padding: 24, background: '#f5f5f5', minHeight: '100vh' }}>
          <div style={{ background: '#fff', padding: 24, borderRadius: 8, minHeight: '100%' }}>
            <Routes>
              <Route path="/" element={<Navigate to="/dataset" replace />} />
              <Route path="/dataset" element={<Dataset />} />
              <Route path="/dataset/:id" element={<DatasetDetail />} />
              <Route path="/task" element={<Task />} />
              <Route path="/report/:taskId" element={<Report />} />
              <Route path="/single-jump" element={<SingleJump />} />
              <Route path="/multi-hop" element={<MultiHop />} />
              <Route path="/qa-gen" element={<QaGen />} />
              <Route path="/config" element={<Config />} />
            </Routes>
          </div>
        </Content>
      </Layout>
    </Layout>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AppLayout />
    </BrowserRouter>
  )
}
