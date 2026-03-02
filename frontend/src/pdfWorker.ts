import { pdfjs } from "react-pdf";

let workerConfigured = false;

export function ensurePdfWorker(): void {
  if (workerConfigured) return;
  pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.js";
  workerConfigured = true;
}
