import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from '@/components/Layout'
import Dashboard from '@/pages/Dashboard'
import Providers from '@/pages/Providers'
import Scripts from '@/pages/Scripts'
import { DataPage } from './pages/Data'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/data" element={<DataPage />} />
        <Route path="/providers" element={<Providers />} />
        <Route path="/scripts" element={<Scripts />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
