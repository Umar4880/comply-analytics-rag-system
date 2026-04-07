"use client";

import { chatStream } from "../lib/api";
import { useChatStore } from "../store/chatStore";

export function useStream() {
  const appendStreamToken = useChatStore((s) => s.appendStreamToken);
  const setStreamingStatus = useChatStore((s) => s.setStreamingStatus);
  const finalizeStream = useChatStore((s) => s.finalizeStream);
  const cancelStreaming = useChatStore((s) => s.cancelStreaming);

  const send = async (input: {
    query: string;
    sessionId: string | null;
    userId: string;
    docScope: string | null;
  }) => {
    let response: Response;
    try {
      response = await chatStream({
        query: input.query,
        session_id: input.sessionId,
        user_id: input.userId,
        doc_scope: input.docScope,
      });
    } catch (e) {
      cancelStreaming();
      throw new Error(
        "Failed to fetch backend. Ensure FastAPI is running on http://localhost:8000 and CORS is enabled."
      );
    }

    if (!response.ok || !response.body) {
      cancelStreaming();
      throw new Error("Streaming request failed");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop() || "";

      for (const event of events) {
        if (!event.startsWith("data: ")) continue;
        const raw = event.slice(6);
        if (!raw.trim()) continue;

        const data = JSON.parse(raw);
        if (data.type === "status") {
          // Show status update briefly (will be replaced when tokens start)
          setStreamingStatus(data.status);
        } else if (data.type === "token") {
          appendStreamToken(data.token || "");
        } else if (data.type === "final") {
          finalizeStream(
            data.cited_chunks || [],
            data.citation_details || [],
            data.confidence || 0,
            data.session_id,
            data.model_used,
            data.session_title
          );
        } else if (data.type === "error") {
          cancelStreaming();
          const message = data.detail ? `${data.error || "Stream error"}: ${data.detail}` : (data.error || "Stream error");
          throw new Error(message);
        }
      }
    }
  };

  return { send };
}
