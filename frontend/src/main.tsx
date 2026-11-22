import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import "@fontsource/barlow/400.css";
import "@fontsource/barlow/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import { App } from "./routes/App";
import "./style.css";
const mount = document.getElementById("root");
if (mount)
  createRoot(mount).render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { staleTime: 15000, retry: 1 } },
        })
      }
    >
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>,
  );
