import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { initLang } from "./i18n/index.js";
import "./styles.css";

initLang();   // ?lang= in the URL, else the saved choice, else English (the default)
createRoot(document.getElementById("root")).render(<App />);
