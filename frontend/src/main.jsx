import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { VerifyPage } from "./tabs/trustpass.jsx";
import { initLang } from "./i18n/index.js";
import "./styles.css";

initLang();   // ?lang= in the URL, else the saved choice, else English (the default)
// A Trust Pass QR opens /?verify=<code>: a public, login-free check page for the landlord or bank.
const verify = new URLSearchParams(window.location.search).get("verify");
createRoot(document.getElementById("root")).render(verify ? <VerifyPage code={verify} /> : <App />);
