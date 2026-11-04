/// <reference types="vite/client" />

interface Window {
  /** Injected by the desktop app (pywebview); absent when the editor runs in a browser. */
  pywebview?: {
    api?: {
      save_json?: (filename: string, content: string) => Promise<string | null>;
    };
  };
}
