"""Extract bounded plain text from supported upload formats."""
import io
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path

from pypdf import PdfReader

from .ai import AnalysisError

MAX_DOCX_XML_BYTES = 15 * 1024 * 1024
WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract_document_text(raw: bytes, filename: str, content_type: str | None) -> str:
    suffix = Path(filename.strip()).suffix.lower()
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if suffix == ".doc":
        raise AnalysisError(415, "El formato .doc no es compatible. Guarda el archivo como .docx")
    if suffix not in {".pdf", ".docx", ".txt"}:
        suffix = {"application/pdf": ".pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx", "text/plain": ".txt"}.get(mime, suffix)
    if suffix == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(raw))
            if getattr(reader, "is_encrypted", False) and not reader.decrypt(""):
                raise AnalysisError(422, "El PDF está protegido por contraseña. Sube una copia desbloqueada.")
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except AnalysisError:
            raise
        except Exception as exc:
            raise AnalysisError(422, "No se pudo leer el PDF") from exc
        if not text.strip():
            raise AnalysisError(422, "El PDF no contiene texto seleccionable. OCR no está habilitado")
        return text

    if suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > MAX_DOCX_XML_BYTES:
                    raise AnalysisError(422, "El documento Word es demasiado complejo para analizarlo")
                with archive.open(info) as source:
                    xml = source.read(MAX_DOCX_XML_BYTES + 1)
            if len(xml) > MAX_DOCX_XML_BYTES or b"<!DOCTYPE" in xml.upper():
                raise AnalysisError(422, "El documento Word es demasiado complejo para analizarlo")
            root = ET.fromstring(xml)
            paragraphs = []
            for paragraph in root.iter(f"{WORD_NS}p"):
                parts = []
                for node in paragraph.iter():
                    if node.tag == f"{WORD_NS}t":
                        parts.append(node.text or "")
                    elif node.tag == f"{WORD_NS}tab":
                        parts.append("\t")
                    elif node.tag == f"{WORD_NS}br":
                        parts.append("\n")
                paragraphs.append("".join(parts))
            text = "\n".join(paragraphs)
        except AnalysisError:
            raise
        except (zipfile.BadZipFile, zipfile.LargeZipFile, KeyError, ET.ParseError, RuntimeError, ValueError, OSError, EOFError, zlib.error) as exc:
            raise AnalysisError(422, "No se pudo leer el documento Word") from exc
        if not text.strip():
            raise AnalysisError(422, "El documento Word no contiene texto")
        return text

    if suffix == ".txt":
        try:
            if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
                text = raw.decode("utf-32")
            elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                text = raw.decode("utf-16")
            else:
                try:
                    text = raw.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = raw.decode("cp1252")
        except UnicodeDecodeError as exc:
            raise AnalysisError(422, "No se pudo leer el TXT. Guárdalo con codificación UTF-8 e inténtalo de nuevo.") from exc
        if any(ord(char) < 32 and char not in "\t\n\r" for char in text):
            raise AnalysisError(422, "El archivo TXT no contiene texto válido")
        if not text.strip():
            raise AnalysisError(422, "El archivo TXT está vacío")
        return text

    raise AnalysisError(415, "Solo se admiten archivos PDF, DOCX y TXT")
