import { Routes, Route } from 'react-router-dom'
import Layout from '@/components/Layout'
import Dashboard from '@/pages/Dashboard'
import Tasks from '@/pages/Tasks'
import TaskDetail from '@/pages/TaskDetail'
import Pool from '@/pages/Pool'
import Workers from '@/pages/Workers'
import Providers from '@/pages/Providers'
import Data from '@/pages/Data'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/tasks" element={<Tasks />} />
        <Route path="/tasks/:id" element={<TaskDetail />} />
        <Route path="/pool" element={<Pool />} />
        <Route path="/workers" element={<Workers />} />
        <Route path="/providers" element={<Providers />} />
        <Route path="/data" element={<Data />} />
      </Route>
    </Routes>
  )
}
