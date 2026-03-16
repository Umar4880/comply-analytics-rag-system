"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { deleteDocument, fetchDocuments, uploadDocument } from "../lib/api";

export function useDocuments() {
  const qc = useQueryClient();

  const documentsQuery = useQuery({
    queryKey: ["documents"],
    queryFn: fetchDocuments,
  });

  const uploadMutation = useMutation({
    mutationFn: uploadDocument,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["documents"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteDocument,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["documents"] });
    },
  });

  return { documentsQuery, uploadMutation, deleteMutation };
}
