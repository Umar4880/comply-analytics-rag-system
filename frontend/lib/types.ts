export type Session = {
  session_id: string;
  title: string;
  updated_at: string;
  message_count: number;
};

export type Message = {
  role: "user" | "assistant";
  content: string;
  cited_chunks: string[];
  created_at?: string;
  confidence?: number;
};

export type DocumentItem = {
  doc_id: string;
  doc_name: string;
  doc_type: string;
  total_pages: number;
  ingested_at: string;
  chunk_count: number;
};

export type ChatFinalEvent = {
  cited_chunks: string[];
  session_id: string;
  confidence: number;
  from_cache: boolean;
};

export type ChartSeries = {
  name: string;
  value: number;
};
