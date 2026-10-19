import { HashRouter, Route, Routes, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import HomePage from "./pages/HomePage";
import PracticePage from "./pages/PracticePage";
import OralPracticePage from "./pages/OralPracticePage";
import OralTestPage from "./pages/OralTestPage";
import ScenarioPage from "./pages/ScenarioPage";
import TutorPage from "./pages/TutorPage";
import ReadAlongPage from "./pages/ReadAlongPage";
import MemorizePage from "./pages/MemorizePage";
import MemorizeStudyPage from "./pages/MemorizeStudyPage";
import MemorizeReviewPage from "./pages/MemorizeReviewPage";
import MistakesPage from "./pages/MistakesPage";
import StudyLogPage from "./pages/StudyLogPage";
import ImportPage from "./pages/ImportPage";
import SettingsPage from "./pages/SettingsPage";
import MorePage from "./pages/MorePage";
import { initTtsVoiceFromConfig } from "./lib/audio";

export default function App() {
  // 应用启动时从配置加载 TTS 音色
  initTtsVoiceFromConfig();

  return (
    <HashRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<HomePage />} />
          <Route path="practice" element={<PracticePage />} />
          {/* 旧模块入口重定向 */}
          <Route path="quiz" element={<Navigate to="/memorize" replace />} />
          <Route path="oral" element={<OralPracticePage />} />
          <Route path="oral-test" element={<OralTestPage />} />
          <Route path="scenario" element={<ScenarioPage />} />
          <Route path="tutor" element={<TutorPage />} />
          <Route path="readalong" element={<ReadAlongPage />} />
          <Route path="memorize" element={<MemorizePage />} />
          <Route path="memorize/study" element={<MemorizeStudyPage />} />
          <Route path="memorize/review" element={<MemorizeReviewPage />} />
          <Route path="mistakes" element={<MistakesPage />} />
          <Route path="study-log" element={<StudyLogPage />} />
          <Route path="import" element={<ImportPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="more" element={<MorePage />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}
