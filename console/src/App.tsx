import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AppProvider } from "./context/AppContext";
import { InvestigationProvider } from "./context/InvestigationContext";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import AtlasPage from "./pages/atlas/AtlasPage";
import ProbePage from "./pages/probe/ProbePage";
import LensPage from "./pages/lens/LensPage";
import ChatPage from "./pages/chat/ChatPage";

export default function App() {
  return (
    <BrowserRouter>
      <AppProvider>
        <InvestigationProvider>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<Dashboard />} />
              <Route path="chat" element={<ChatPage />} />
              <Route path="atlas" element={<AtlasPage />} />
              <Route path="probe" element={<ProbePage />} />
              <Route path="lens" element={<LensPage />} />
            </Route>
          </Routes>
        </InvestigationProvider>
      </AppProvider>
    </BrowserRouter>
  );
}
