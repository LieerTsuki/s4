import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";
import "./styles.css";

const client = new QueryClient({
  defaultOptions: {
    queries: { retry: false, staleTime: 5000, refetchOnWindowFocus: true },
  },
});
createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={client}>
    <HashRouter>
      <App />
    </HashRouter>
  </QueryClientProvider>,
);
