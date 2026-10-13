import io
import zipfile

import pytest

from app.ai import AnalysisError
from app.document_text import extract_document_text


def word_file() -> bytes:
    output = io.BytesIO()
    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p><w:r><w:t>Entrega final</w:t></w:r></w:p>'
        '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>20 de noviembre</w:t></w:r></w:p>'
        '</w:tc></w:tr></w:tbl></w:body></w:document>'
    )
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return output.getvalue()


def test_docx_extracts_paragraphs_and_table_cells():
    assert extract_document_text(word_file(), "Programa.DOCX", None) == "Entrega final\n20 de noviembre"


def test_docx_includes_headers_footers_and_footnotes():
    output = io.BytesIO()
    def xml(value):
        return (f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f'<w:p><w:r><w:t>{value}</w:t></w:r></w:p></w:document>')
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/header1.xml", xml("Periodo 2026"))
        archive.writestr("word/document.xml", xml("Entregar informe"))
        archive.writestr("word/footer1.xml", xml("Fecha 20 de noviembre"))
        archive.writestr("word/footnotes.xml", xml("Anexo evaluado"))
    assert extract_document_text(output.getvalue(), "programa.docx", None) == (
        "Periodo 2026\nEntregar informe\nFecha 20 de noviembre\nAnexo evaluado")


def test_docx_rejects_oversized_additional_part():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("word/header1.xml", b"x" * (15 * 1024 * 1024))
    with pytest.raises(AnalysisError, match="demasiado complejo"):
        extract_document_text(output.getvalue(), "programa.docx", None)


def test_txt_decodes_utf8_bom_and_windows_encoding():
    assert extract_document_text(b"\xef\xbb\xbfEntrega ma\xc3\xb1ana", "nota.txt", "text/plain") == "Entrega mañana"
    assert extract_document_text(b"Entrega ma\xf1ana", "nota.txt", "text/plain") == "Entrega mañana"


@pytest.mark.parametrize("filename,raw,status", [
    ("archivo.docx", b"no es un zip", 422),
    ("archivo.txt", b"\x00\x01", 422),
    ("archivo.txt", b" \n", 422),
    ("archivo.doc", b"archivo antiguo", 415),
    ("archivo.png", b"imagen", 415),
])
def test_invalid_or_unsupported_files_are_rejected(filename, raw, status):
    with pytest.raises(AnalysisError) as exc:
        extract_document_text(raw, filename, None)
    assert exc.value.status_code == status


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-16-be", "utf-32", "utf-32-be"])
def test_txt_supports_unicode_encodings_with_explicit_byte_order_marks(encoding):
    text = "Exposición: entrega mañana, 20 de noviembre de 2026."
    raw = text.encode(encoding)
    if encoding == "utf-16-be":
        raw = b"\xfe\xff" + raw
    elif encoding == "utf-32-be":
        raw = b"\x00\x00\xfe\xff" + raw
    assert extract_document_text(raw, "Programa.TXT", "text/plain; charset=utf-8") == text


@pytest.mark.parametrize("filename,mime", [("documento", "text/plain"), ("archivo.bin", "text/plain; charset=utf-8")])
def test_txt_can_be_recognized_by_mime_when_extension_is_unavailable(filename, mime):
    assert extract_document_text(b"Entrega final", filename, mime) == "Entrega final"


def test_docx_without_extension_is_recognized_by_mime():
    assert extract_document_text(word_file(), "documento", "application/vnd.openxmlformats-officedocument.wordprocessingml.document") == "Entrega final\n20 de noviembre"


def test_pdf_without_extension_is_recognized_by_mime(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr("app.document_text.PdfReader", lambda _: SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda: "Entrega final")]))
    assert extract_document_text(b"fixture", "documento", "application/pdf") == "Entrega final"


def test_pdf_stops_when_extracted_text_exceeds_limit(monkeypatch):
    from types import SimpleNamespace
    def second_page():
        raise AssertionError("The next PDF page should not be read")
    monkeypatch.setattr("app.document_text.PdfReader", lambda _: SimpleNamespace(pages=[
        SimpleNamespace(extract_text=lambda: "x" * 50_001),
        SimpleNamespace(extract_text=second_page),
    ]))
    with pytest.raises(AnalysisError, match="50 000"):
        extract_document_text(b"fixture", "large.pdf", "application/pdf")


def test_password_protected_pdf_has_an_actionable_error():
    from pypdf import PdfWriter
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("test-password")
    writer.write(output)
    with pytest.raises(AnalysisError, match="contraseña") as error:
        extract_document_text(output.getvalue(), "protegido.pdf", "application/pdf")
    assert error.value.status_code == 422


def test_broken_unicode_txt_is_rejected_instead_of_decoded_as_binary():
    with pytest.raises(AnalysisError):
        extract_document_text(b"\xff\xfeA", "archivo.txt", "text/plain")


def test_legacy_word_is_not_mistaken_for_docx_by_its_mime():
    with pytest.raises(AnalysisError) as error:
        extract_document_text(b"legacy", "archivo.doc", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert error.value.status_code == 415
