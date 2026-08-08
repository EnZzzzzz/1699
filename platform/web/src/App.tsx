import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from '@/components/Layout'
import Dashboard from '@/pages/Dashboard'
import Tasks from '@/pages/Tasks'
import Providers from '@/pages/Providers'
import Dispatcher from '@/pages/Dispatcher'
import { DataPage } from './pages/Data'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/tasks" element={<Tasks />} />
        <Route path="/data" element={<DataPage />} />
        <Route path="/providers" element={<Providers />} />
        <Route path="/dispatcher" element={<Dispatcher />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
