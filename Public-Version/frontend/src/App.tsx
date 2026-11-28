import React from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AdminAuthGate } from "./components/AdminAuthGate";
import { AdminAuthProvider } from "./context/AdminAuthContext";
import { DashboardPage } from "./pages/DashboardPage";
import { OpsCenterPage } from "./pages/OpsCenterPage";
import { PublicTasksPage } from "./pages/PublicTasksPage";
import { ClientLoadPage } from "./pages/ClientLoadPage";

export const App: React.FC = () => {
  return (
    <AdminAuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<PublicTasksPage />} />
          <Route path="/client" element={<ClientLoadPage />} />
          <Route
            path="/ops"
            element={
              <AdminAuthGate>
                <OpsCenterPage />
              </AdminAuthGate>
            }
          />
          <Route
            path="/benchmark"
            element={
              <AdminAuthGate>
                <DashboardPage />
              </AdminAuthGate>
            }
          />
          <Route
            path="/admin"
            element={
              <AdminAuthGate>
                <Navigate to="/ops" replace />
              </AdminAuthGate>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AdminAuthProvider>
  );
};

export default App;
