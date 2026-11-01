"""Resumo e relatório em PDF de observabilidade, usados pelo console de testes."""
from fastapi.responses import Response

from app.observability.metrics import load_records, project, summarize
from app.observability.report import build_pdf


def build_summary() -> dict:
    summary = summarize(load_records())
    summary["projection"] = project(summary)
    return summary


def pdf_response() -> Response:
    return Response(build_pdf(build_summary()), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="delta-observabilidade.pdf"'})
