import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AppProvider } from "./context/AppContext";
import { InvestigationProvider } from "./context/InvestigationContext";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import AtlasPage from "./pages/atlas/AtlasPage";
import ProbePage from "./pages/probe/ProbePage";
import LensPage from "./pages/lens/LensPage";
import ChatPage from "./pages/chat/ChatPage";
import NexusPage from "./pages/nexus/NexusPage";
import LoginPage from "./pages/LoginPage";

export default function App() {
  return (
    <BrowserRouter>
      <AppProvider>
        <InvestigationProvider>
          <Routes>
            <Route path="login" element={<LoginPage />} />
            <Route element={<Layout />}>
              <Route index element={<Dashboard />} />
              <Route path="chat" element={<ChatPage />} />
              <Route path="atlas" element={<AtlasPage />} />
              <Route path="probe" element={<ProbePage />} />
              <Route path="lens" element={<LensPage />} />
              <Route path="nexus" element={<NexusPage />} />
            </Route>
          </Routes>
        </InvestigationProvider>
      </AppProvider>
    </BrowserRouter>
  );
}
