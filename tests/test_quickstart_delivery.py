"""학생의 fresh clone에서 데모와 실제 PDF 입력이 작동하는지 검증한다."""
import importlib.util
import shlex
import subprocess
import sys
from pathlib import Path

import pymupdf as fitz
from fastapi.testclient import TestClient
import pytest

import doctor
import compile as compiler
import ingest
import export_graph
from wiki_app.api import create_app

ROOT = Path(__file__).resolve().parents[1]


def test_shipped_seed_is_searchable_without_personal_data():
    seed = ROOT / 'examples/course-seed-wiki'
    assert (seed / 'wiki').is_dir(), 'fresh clone에 데모 데이터가 누락됐습니다.'
    client = TestClient(create_app(wiki_root=seed / 'wiki'))
    assert client.get('/api/index').json()['total_pages'] == 5
    assert client.get('/api/search', params={'q': '인터뷰'}).json()['total'] > 0
    assert client.get('/api/page/user-interview').status_code == 200
    for path in seed.rglob('*'):
        if path.is_file():
            ignored = subprocess.run(['git', 'check-ignore', str(path)], cwd=ROOT, capture_output=True)
            assert ignored.returncode == 1, f'공개 데모가 gitignore에 제외됨: {path.name}'


def test_guided_demo_cannot_claim_success_when_seed_is_missing(tmp_path):
    output = doctor.render_guided(tmp_path, 'demo')
    if 'Next action:' not in output:
        assert '누락' in output or 'missing' in output.lower()
        return
    action = output.rsplit(': ', 1)[1].replace('uv run python', shlex.quote(sys.executable))
    result = subprocess.run(action, shell=True, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'Demo installation verification OK' not in result.stdout


def _paper_module():
    path = ROOT / 'scripts/download_paper.py'
    assert path.is_file(), '존재하지 않는 paper.pdf 대신 실제 논문을 받는 명령이 필요합니다.'
    spec = importlib.util.spec_from_file_location('download_paper', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_paper_download_rejects_html_without_saving_a_fake_pdf(tmp_path, monkeypatch):
    module = _paper_module()
    import httpx
    monkeypatch.setattr(module.httpx, 'get', lambda *a, **k: httpx.Response(
        200, content=b'<html>service unavailable</html>', request=httpx.Request('GET', module.PAPER_URL)))
    target = tmp_path / 'paper.pdf'
    with pytest.raises(ValueError):
        module.download_paper(target)
    assert not target.exists()


def test_paper_download_preserves_existing_different_document(tmp_path):
    module = _paper_module()
    target = tmp_path / 'paper.pdf'
    target.write_bytes(b'MY DOCUMENT')
    with pytest.raises(ValueError):
        module.download_paper(target)
    assert target.read_bytes() == b'MY DOCUMENT'


@pytest.fixture
def isolated_brain(tmp_path, monkeypatch):
    for module, values in [
        (compiler, dict(ROOT=tmp_path, WIKI_DIR=tmp_path/'wiki', INDEX_FILE=tmp_path/'index.md')),
        (ingest, dict(WIKI_ROOT=tmp_path, RAW_DIR=tmp_path/'raw', STATE_FILE=tmp_path/'.ingest_state.json')),
        (export_graph, dict(WIKI_DIR=tmp_path/'wiki', OUTPUT=tmp_path/'wiki/graph.json')),
    ]:
        for key, value in values.items():
            monkeypatch.setattr(module, key, value)
    (tmp_path/'raw/docs').mkdir(parents=True)
    monkeypatch.setattr(compiler.llm_client, 'load_llm_config', lambda: {'api_key_env': 'EDU_TEST_KEY'})
    monkeypatch.setenv('EDU_TEST_KEY', 'synthetic-no-network')
    return tmp_path


def test_explicit_rule_never_calls_model_even_with_a_key(isolated_brain, monkeypatch):
    raw = isolated_brain/'raw/docs/note.md'
    raw.write_text('# 제공 자료\n\nPublic test input', encoding='utf-8')
    async def forbidden(*args):
        pytest.fail('RULE 실습이 유료 모델을 호출하면 안 됩니다.')
    monkeypatch.setattr(compiler, '_page_by_llm', forbidden)
    monkeypatch.setattr(sys, 'argv', ['compile.py', '--rule'])
    assert compiler.main() == 0
    assert 'RULE' in next((isolated_brain/'wiki/concepts').glob('*.md')).read_text()


def test_pdf_and_its_extracted_copy_compile_as_one_document(isolated_brain, monkeypatch, capsys):
    source = isolated_brain/'input.pdf'
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), 'Attention Is All You Need\nPublic PDF fixture')
        doc.save(source)
    ingest.ingest_file(source)
    monkeypatch.delenv('EDU_TEST_KEY')
    monkeypatch.setattr(sys, 'argv', ['compile.py'])
    assert compiler.main() == 0
    assert '[compile] 메모 1건' in capsys.readouterr().out
    assert len(list((isolated_brain/'wiki/concepts').glob('*.md'))) == 1
    assert ingest.find_unprocessed() == []


def test_bad_pdf_does_not_abort_other_documents(isolated_brain, monkeypatch):
    docs = isolated_brain/'raw/docs'
    (docs/'bad.pdf').write_bytes(b'not a PDF')
    (docs/'good.md').write_text('# Good\n\nPublic input', encoding='utf-8')
    monkeypatch.delenv('EDU_TEST_KEY')
    monkeypatch.setattr(sys, 'argv', ['compile.py'])
    assert compiler.main() == 1
    assert len(list((isolated_brain/'wiki/concepts').glob('*.md'))) == 1
    assert [p.name for p in ingest.find_unprocessed()] == ['bad.pdf']


def test_legacy_processed_pdf_does_not_leave_sidecar_pending(isolated_brain, monkeypatch):
    source = isolated_brain/'input.pdf'
    with fitz.open() as doc:
        doc.new_page().insert_text((72, 72), 'Attention Is All You Need')
        doc.save(source)
    raw = ingest.ingest_file(source)
    ingest.save_state({'processed': [raw.relative_to(isolated_brain).as_posix()]})
    monkeypatch.setattr(sys, 'argv', ['compile.py', '--rule'])
    assert compiler.main() == 0
    assert ingest.find_unprocessed() == []
    assert len(list((isolated_brain/'wiki/concepts').glob('*.md'))) == 1


def test_download_cli_handles_a_broken_pdf_without_traceback(tmp_path, monkeypatch, capsys):
    module = _paper_module()
    target = tmp_path/'bad.pdf'
    target.write_bytes(b'%PDF-1.7\nnot a real document')
    monkeypatch.setattr(sys, 'argv', ['download_paper.py', '--output', str(target)])
    assert module.main() == 1
    assert '다운로드 실패' in capsys.readouterr().err
    assert target.read_bytes() == b'%PDF-1.7\nnot a real document'


def test_course_seed_keeps_valid_raw_sources_for_claims(isolated_brain):
    from lib import claim_ledger
    assert compiler.do_seed(False) == 0
    wiki = isolated_brain/'wiki'
    records = claim_ledger.build_claim_ledger(claim_ledger.wiki_page_slugs(wiki), wiki_root=wiki)
    assert records
    assert all(record.raw_path.startswith('raw/') for record in records)
    assert ingest.find_unprocessed() == []
