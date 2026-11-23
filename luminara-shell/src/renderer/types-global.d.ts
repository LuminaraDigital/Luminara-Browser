import type { LuminaraShellApi } from "../shared/types";

declare global {
  interface Window {
    luminaraShell: LuminaraShellApi;
  }
}

export {};
