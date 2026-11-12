import React from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ClientPage } from "./pages/ClientPage";
import { DashboardPage } from "./pages/DashboardPage";

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/client" element={<ClientPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
};

export default App;

