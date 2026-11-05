/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_JAM_MEMBER_TOKEN?: string;
  readonly VITE_SYNC_PARTICIPANT_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
