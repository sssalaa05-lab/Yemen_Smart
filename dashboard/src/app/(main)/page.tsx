import DashboardPage from './dashboard/page';

// The trading dashboard opens DIRECTLY at "/" — no login gate.
// (Paper-trading demo; the API gateway is auth-free by design.
// The classic login screen remains available at /login.)
export default function Home() {
  return <DashboardPage />;
}
