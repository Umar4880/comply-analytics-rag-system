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
  citation_details?: CitationDetail[];
  created_at?: string;
  confidence?: number;
  model_used?: string;
};

export type CitationDetail = {
  chunk_id: string;
  doc_name: string;
  section: string;
  page_start: number;
  page_end: number;
  label: string;
  display: string;
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
  citation_details?: CitationDetail[];
  session_id: string;
  session_title?: string;
  confidence: number;
  model_used?: string;
  from_cache: boolean;
};

export type ChartSeries = {
  name: string;
  value: number;
};
