import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

// 不用 StrictMode：录音/TTS 等副作用 effect 会被双调用，干扰真实设备
ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
