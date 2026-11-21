import React from "react";
import ReactDOM from "react-dom/client";
import { MantineProvider, createTheme, localStorageColorSchemeManager } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import "./app.css";
import App from "./App";

const theme = createTheme({
  primaryColor: "indigo",
  defaultRadius: "md",
  fontFamily: "Inter, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
  fontFamilyMonospace: "ui-monospace, SFMono-Regular, Consolas, monospace",
  headings: { fontWeight: "650" },
  components: {
    Card: { defaultProps: { withBorder: true, radius: "md", padding: "lg" } },
    Badge: { defaultProps: { radius: "sm" } },
  },
});

const colorSchemeManager = localStorageColorSchemeManager({ key: "case-review-scheme" });

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="light" colorSchemeManager={colorSchemeManager}>
      <Notifications position="top-right" />
      <App />
    </MantineProvider>
  </React.StrictMode>,
);
