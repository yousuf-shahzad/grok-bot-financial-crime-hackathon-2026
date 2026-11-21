import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@/styles/globals.css";
import App from "./App";

try {
  if (localStorage.getItem("cr-dark") === "1") document.documentElement.classList.add("dark");
} catch { /* storage may be blocked */ }

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
