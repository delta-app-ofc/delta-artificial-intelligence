"""Catálogo fechado e leitura de artigos públicos, sem receber URLs do modelo."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import ssl

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator


MAX_RESPONSE_BYTES = 512_000
MAX_TEXT_CHARS = 60_000


class ExternalSourceError(ValueError):
    """Falha pública segura de acesso ou de contrato da fonte."""


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    url: str
    topic: str
    published_at: str | None
    content_id: str
    audiences: tuple[str, ...]
    language: str


SOURCES = {
    "midr-water-conservation": Source(
        id="midr-water-conservation",
        title="Uso consciente da água — Ministério da Integração e do Desenvolvimento Regional",
        url=("https://www.gov.br/mdr/pt-br/assuntos/seguranca-hidrica/projeto-sao-francisco/"
             "meio-ambiente-preservado/uso-consciente-da-agua"),
        topic="water_conservation",
        published_at=None,
        content_id="parent-fieldname-text",
        audiences=("residential", "organizational"),
        language="pt-BR",
    ),
    "epa-residential-saving": Source(
        id="epa-residential-saving",
        title="Start Saving — US EPA",
        url="https://www.epa.gov/watersense/start-saving",
        topic="water_conservation",
        published_at="2017-01-16",
        content_id="main",
        audiences=("residential",),
        language="en",
    ),
    "epa-commercial-facilities": Source(
        id="epa-commercial-facilities",
        title="Types of Facilities — US EPA",
        url="https://www.epa.gov/watersense/types-facilities",
        topic="commercial_efficiency",
        published_at="2017-01-16",
        content_id="main",
        audiences=("organizational",),
        language="en",
    ),
}


def list_sources() -> list[dict]:
    """Lista somente os metadados públicos; não acessa a internet."""
    return [
        {key: value for key, value in asdict(source).items() if key != "content_id"}
        for source in SOURCES.values()
    ]


class ExternalDocument(BaseModel):
    """Contrato validado também pelo cliente, antes de indexar qualquer conteúdo."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    source_id: str
    title: str
    url: str
    topic: str
    published_at: str | None
    audiences: list[str]
    language: str
    collected_at: str
    revision: str
    text: str = Field(min_length=200, max_length=MAX_TEXT_CHARS)

    @model_validator(mode="after")
    def validate_provenance(self):
        """Recusa fontes desconhecidas, metadados trocados e revisões inválidas."""
        source = SOURCES.get(self.source_id)
        if source is None or any(
            getattr(self, field) != getattr(source, field)
            for field in ("title", "url", "topic", "published_at", "language")
        ) or tuple(self.audiences) != source.audiences:
            raise ValueError("Fonte externa fora do catálogo aprovado.")
        if hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.revision:
            raise ValueError("Revisão externa incompatível com o conteúdo.")
        collected = datetime.fromisoformat(self.collected_at)
        if collected.tzinfo is None:
            raise ValueError("A coleta deve informar o fuso horário.")
        return self


class ArticleParser(HTMLParser):
    """Extrai apenas o artigo selecionado; ignora menus, scripts e estilos."""

    _VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                  "link", "meta", "param", "source", "track", "wbr"}
    _IGNORED_TAGS = {"script", "style", "nav", "footer", "noscript", "iframe"}
    _BLOCK_TAGS = {"p", "li", "div", "section", "h1", "h2", "h3", "h4", "br"}

    def __init__(self, content_id: str):
        super().__init__(convert_charrefs=True)
        self.content_id = content_id
        self.stack: list[tuple[str, bool]] = []
        self.target_depth: int | None = None
        self.parts: list[str] = []
        self.found = False

    def handle_starttag(self, tag, attrs):
        ignored = tag in self._IGNORED_TAGS or any(item[1] for item in self.stack)
        if tag not in self._VOID_TAGS:
            self.stack.append((tag, ignored))
            if dict(attrs).get("id") == self.content_id and not ignored:
                self.target_depth = len(self.stack)
                self.found = True
        if self.target_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.target_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n")
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                self.stack = self.stack[:index]
                break
        if self.target_depth and len(self.stack) < self.target_depth:
            self.target_depth = None

    def handle_data(self, data):
        if self.target_depth and not any(item[1] for item in self.stack):
            self.parts.append(data)

    def text(self) -> str:
        """As linhas pertencem ao texto extraído, não ao HTML original."""
        lines = (" ".join(line.split()) for line in "".join(self.parts).splitlines())
        return "\n".join(line for line in lines if line)


def read_source(source_id: str, *, timeout: float = 10, client=None) -> ExternalDocument:
    """Lê somente uma URL cadastrada, com TLS, limite de bytes e sem redirecionar."""
    source = SOURCES.get(source_id)
    if source is None:
        raise ExternalSourceError("Fonte externa desconhecida.")
    if client is None:
        # Inclui as autoridades confiáveis do Windows, sem desabilitar TLS.
        with httpx.Client(verify=ssl.create_default_context(), follow_redirects=False) as owned:
            return read_source(source_id, timeout=timeout, client=owned)
    try:
        with client.stream("GET", source.url, timeout=timeout, follow_redirects=False,
                           headers={"User-Agent": "Delta-Knowledge/1.0", "Accept": "text/html"}) as response:
            response.raise_for_status()
            if response.headers.get("content-type", "").split(";")[0].strip() != "text/html":
                raise ExternalSourceError("Formato externo não suportado.")
            body = bytearray()
            for block in response.iter_bytes():
                body.extend(block)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ExternalSourceError("Página externa acima do limite permitido.")
            parser = ArticleParser(source.content_id)
            parser.feed(body.decode(response.encoding or "utf-8", errors="strict"))
        text = parser.text()
        if not parser.found or len(text) < 200 or len(text) > MAX_TEXT_CHARS:
            raise ExternalSourceError("Artigo externo ausente ou inválido.")
        return ExternalDocument(
            source_id=source.id, title=source.title, url=source.url, topic=source.topic,
            published_at=source.published_at, audiences=list(source.audiences), language=source.language,
            collected_at=datetime.now(timezone.utc).isoformat(),
            revision=hashlib.sha256(text.encode("utf-8")).hexdigest(), text=text,
        )
    except (httpx.HTTPError, UnicodeError, ValueError) as error:
        raise ExternalSourceError("Não foi possível consultar a fonte externa.") from error
