import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { VerifyPage } from "./tabs/trustpass.jsx";
import { EvidenceVerifyPage } from "./tabs/EvidencePassport.jsx";
import { initLang } from "./i18n/index.js";
import "./styles.css";

initLang();   // ?lang= in the URL, else the saved choice, else English (the default)
// A Trust Pass QR opens /?verify=<code>: a public, login-free check page for the landlord or bank.
const qs = new URLSearchParams(window.location.search);
const verify = qs.get("verify");
const evidence = qs.get("evidence");   // Payment Evidence Passport QR: same idea, separate public page
createRoot(document.getElementById("root")).render(evidence ? <EvidenceVerifyPage code={evidence} /> : verify ? <VerifyPage code={verify} /> : <App />);
