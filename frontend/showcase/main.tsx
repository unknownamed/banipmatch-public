import React from "react";
import ReactDOM from "react-dom/client";
import archive from "../../docs/experiments/engine-evaluation-2026-11-08/showcase.json";
import { Showcase } from "./Showcase";
import type { Archive } from "./model";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Showcase archive={archive as unknown as Archive} />
  </React.StrictMode>,
);
