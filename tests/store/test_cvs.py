import io
import zipfile

import pytest

from prospector.store.cvs import MAX_CV_BYTES, CvRepo, sniff

PDF = b"%PDF-1.7\n" + b"x" * 100


def docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


@pytest.fixture
def repo(wctx, tmp_path):
    return CvRepo(wctx.conn, tmp_path / "cv")


def test_sniff():
    assert sniff(PDF) == "pdf" and sniff(docx()) == "docx"


def test_cv_add_pdf_and_docx(repo):
    a = repo.add("English, backend", "en", "cv.pdf", PDF)
    b = repo.add("French, PFE", "fr", "cv-fr.docx", docx())
    cvs = {c.id: c for c in repo.list()}
    assert cvs[a].is_main and not cvs[b].is_main
    assert repo.path(cvs[a]).read_bytes() == PDF and repo.path(cvs[a]).name.endswith(".pdf")
    assert cvs[a].stored_name != "cv.pdf" and len(cvs[a].stored_name) > 30
    assert cvs[b].content_type.endswith("wordprocessingml.document")


@pytest.mark.parametrize("data", [b"MZ\x90\x00" + b"x" * 50, b"", b"PK\x03\x04garbage"])
def test_cv_rejects_fake_and_empty(repo, data):
    with pytest.raises(ValueError):
        repo.add("x", "en", "x.pdf", data)
    assert repo.list() == []


def test_zip_without_document_rejected(repo):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("other.txt", "hi")
    with pytest.raises(ValueError):
        repo.add("x", "en", "x.docx", buf.getvalue())


def test_cv_rejects_oversize(repo):
    with pytest.raises(ValueError):
        repo.add("x", "en", "big.pdf", b"%PDF-" + b"x" * (MAX_CV_BYTES - 4))
    assert repo.add("x", "en", "ok.pdf", b"%PDF-" + b"x" * (MAX_CV_BYTES - 5))


def test_cv_main_moves_on_delete(repo):
    a = repo.add("A", "en", "a.pdf", PDF)
    b = repo.add("B", "en", "b.pdf", PDF)
    repo.set_main(b)
    assert [c.id for c in repo.list() if c.is_main] == [b]
    path = repo.path(repo.get(b))
    repo.delete(b)
    assert not path.exists() and repo.get(a).is_main


def test_cv_replace(repo):
    a = repo.add("A", "en", "a.pdf", PDF)
    old = repo.path(repo.get(a))
    repo.replace(a, "new.docx", docx())
    cv = repo.get(a)
    assert cv.filename == "new.docx" and not old.exists() and repo.path(cv).name.endswith(".docx")
    with pytest.raises(ValueError):
        repo.replace(a, "bad.pdf", b"nope")
    assert repo.get(a).filename == "new.docx"
