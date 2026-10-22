import { lazy, type ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth'
import Layout from './components/Layout'
import { Spinner } from './components/ui'
import Login from './pages/Login'
import type { Role } from './types'

const AssignGoals = lazy(() => import('./pages/AssignGoals'))
const DailyUpdate = lazy(() => import('./pages/DailyUpdate'))
const GoalDetail = lazy(() => import('./pages/GoalDetail'))
const GoalReview = lazy(() => import('./pages/GoalReview'))
const Goals = lazy(() => import('./pages/Goals'))
const History = lazy(() => import('./pages/History'))
const MyDashboard = lazy(() => import('./pages/MyDashboard'))
const People = lazy(() => import('./pages/People'))
const ReportDetail = lazy(() => import('./pages/ReportDetail'))
const Reports = lazy(() => import('./pages/Reports'))
const Settings = lazy(() => import('./pages/Settings'))
const TeamDashboard = lazy(() => import('./pages/TeamDashboard'))

function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { user } = useAuth()
  return user && roles.includes(user.role) ? <>{children}</> : <Navigate to="/" replace />
}

function Home() {
  const { user } = useAuth()
  return user?.role === 'employee' ? <MyDashboard /> : <TeamDashboard />
}

export default function App() {
  const { user, loading } = useAuth()
  if (loading) return <Spinner className="min-h-screen" />
  if (!user) {
    return (
      <Routes>
        <Route path="*" element={<Login />} />
      </Routes>
    )
  }
  return (
    <Routes>
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="me" element={<MyDashboard />} />
        <Route path="update" element={<RequireRole roles={['employee', 'manager']}><DailyUpdate /></RequireRole>} />
        <Route path="update/:logId" element={<RequireRole roles={['employee', 'manager']}><DailyUpdate /></RequireRole>} />
        <Route path="goals" element={<Goals />} />
        <Route path="goals/assign" element={<RequireRole roles={['manager', 'admin']}><AssignGoals /></RequireRole>} />
        <Route path="goals/review" element={<RequireRole roles={['manager', 'admin']}><GoalReview /></RequireRole>} />
        <Route path="goals/:id" element={<GoalDetail />} />
        <Route path="history" element={<History />} />
        <Route path="team/history" element={<History />} />
        <Route path="reports" element={<Reports />} />
        <Route path="reports/:id" element={<ReportDetail />} />
        <Route path="admin/people" element={<RequireRole roles={['admin']}><People /></RequireRole>} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
