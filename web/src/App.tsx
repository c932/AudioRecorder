import { HashRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import HomePage from "./pages/HomePage";
import PracticePage from "./pages/PracticePage";
import QuizPage from "./pages/QuizPage";
import OralHubPage from "./pages/OralHubPage";
import OralTestPage from "./pages/OralTestPage";
import ScenarioPage from "./pages/ScenarioPage";
import TutorPage from "./pages/TutorPage";
import MemorizePage from "./pages/MemorizePage";
import MistakesPage from "./pages/MistakesPage";
import ImportPage from "./pages/ImportPage";
import SettingsPage from "./pages/SettingsPage";
import MorePage from "./pages/MorePage";

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<HomePage />} />
          <Route path="practice" element={<PracticePage />} />
          <Route path="quiz" element={<QuizPage />} />
          <Route path="oral" element={<OralHubPage />} />
          <Route path="oral-test" element={<OralTestPage />} />
          <Route path="scenario" element={<ScenarioPage />} />
          <Route path="tutor" element={<TutorPage />} />
          <Route path="memorize" element={<MemorizePage />} />
          <Route path="mistakes" element={<MistakesPage />} />
          <Route path="import" element={<ImportPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="more" element={<MorePage />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}
