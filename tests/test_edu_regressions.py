"""학생 안내를 따랐을 때 원문 수정, 개인정보, 지도 연결이 실제 결과에 반영되는지."""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import compile as compiler
import ingest
import export_graph
import episode
from lib.pii import find_pii
from wiki_app.api import create_app


@pytest.fixture
def brain(tmp_path, monkeypatch):
    for module, values in [
        (compiler, dict(ROOT=tmp_path, WIKI_DIR=tmp_path/'wiki', INDEX_FILE=tmp_path/'index.md')),
        (ingest, dict(WIKI_ROOT=tmp_path, RAW_DIR=tmp_path/'raw', STATE_FILE=tmp_path/'.ingest_state.json')),
        (export_graph, dict(WIKI_DIR=tmp_path/'wiki', OUTPUT=tmp_path/'wiki/graph.json')),
    ]:
        for key, value in values.items():
            monkeypatch.setattr(module, key, value)
    monkeypatch.setattr(compiler.llm_client, 'load_llm_config', lambda: {'api_key_env': 'EDU_TEST_KEY'})
    monkeypatch.delenv('EDU_TEST_KEY', raising=False)
    append = episode.append
    monkeypatch.setattr(episode, 'append', lambda record: append(record, episodes_dir=tmp_path/'episodes'))
    (tmp_path/'raw/notes').mkdir(parents=True)
    return tmp_path


def compile_now(monkeypatch, *args):
    monkeypatch.setattr(sys, 'argv', ['compile.py', *args])
    return compiler.main()


def test_fixing_raw_updates_existing_page_and_dashboard(brain, monkeypatch):
    raw = brain/'raw/notes/a.md'
    raw.write_text('# 메모\n\n수정 전 문장', encoding='utf-8')
    compile_now(monkeypatch)
    assert ingest.find_unprocessed() == []
    raw.write_text('# 메모\n\n수정 후 문장', encoding='utf-8')
    assert raw in ingest.find_unprocessed()
    client = TestClient(create_app(wiki_root=brain/'wiki'))
    assert client.get('/api/dashboard').json()['attention']['raw_pending'] == 1
    compile_now(monkeypatch)
    pages = list((brain/'wiki/concepts').glob('*.md'))
    assert len(pages) == 1
    assert '수정 후 문장' in pages[0].read_text()
    assert '수정 전 문장' not in pages[0].read_text()
    assert client.get('/api/dashboard').json()['attention']['raw_pending'] == 0


def test_explicit_live_recompile_replaces_rule_page_even_when_model_renames(brain, monkeypatch):
    raw = brain/'raw/notes/a.md'
    raw.write_text('# 메모\n\n내용', encoding='utf-8')
    compile_now(monkeypatch)
    monkeypatch.setenv('EDU_TEST_KEY', 'synthetic-no-network')
    # Only the remote LLM boundary is replaced. Selection, saving, index and graph stay real.
    async def llm_page(f, text):
        return brain/'wiki/tools/new-name.md', '---\ntitle: 요약\nsources: [raw/notes/a.md]\n---\n\nLIVE 요약 결과'
    monkeypatch.setattr(compiler, '_page_by_llm', llm_page)
    compile_now(monkeypatch, '--recompile')
    pages = list((brain/'wiki').glob('*/*.md'))
    assert len(pages) == 1
    assert 'LIVE 요약 결과' in pages[0].read_text()
    assert ingest.find_unprocessed() == []


def test_note_text_never_survives_in_new_episode_after_raw_is_fixed(brain, monkeypatch):
    text = '검토용 더미 주민번호 900101-1234567 확인'
    monkeypatch.setattr(sys, 'argv', ['ingest.py', '--note', text])
    with pytest.raises(SystemExit):
        ingest.main()
    raw = next((brain/'raw/notes').glob('*.md'))
    raw.write_text('민감정보를 제거한 메모', encoding='utf-8')
    ledger = next((brain/'episodes').glob('*.jsonl')).read_text()
    assert '900101-1234567' not in ledger
    assert text not in ledger
    assert json.loads(ledger)['outputs']['saved_path'] == raw.relative_to(brain).as_posix()


@pytest.mark.parametrize('text', ['주민번호900101-1234567', '900101-1234567입니다', '주민번호9001011234567확인'])
def test_pii_is_detected_next_to_korean_letters(text):
    assert find_pii(text) == ['주민등록번호']


def test_mixed_wikilinks_do_not_hide_other_teams_tag_connections(brain):
    wiki = brain/'wiki'
    wiki.mkdir()
    nodes = [dict(id=x, kind='page', title=x, category='concepts') for x in ['cs', 'sourcing', 'marketing1', 'marketing2']]
    links = [dict(source='cs', target='sourcing', kind='wikilink'),
             dict(source='marketing1', target='marketing', kind='tag'),
             dict(source='marketing2', target='marketing', kind='tag'),
             dict(source='cs', target='commerce', kind='tag'),
             dict(source='sourcing', target='commerce', kind='tag')]
    (wiki/'graph.json').write_text(json.dumps(dict(nodes=nodes, links=links)))
    result = TestClient(create_app(wiki_root=wiki)).get('/api/dashboard').json()
    edges = result['knowledge']['graph_links']
    assert {frozenset((e['s'],e['t'])) for e in edges} == {
        frozenset(('cs','sourcing')), frozenset(('marketing1','marketing2'))}
    assert len(edges) == 2  # A shared tag must not duplicate the existing wikilink.


def test_legacy_state_can_be_recompiled_without_losing_other_pages(brain, monkeypatch):
    raw = brain/'raw/notes/legacy.md'
    raw.write_text('# 수정한 원문\n\n새 내용', encoding='utf-8')
    concepts = brain/'wiki/concepts'
    concepts.mkdir(parents=True)
    page = concepts/'old-title.md'
    page.write_text('---\nsources: [raw/notes/legacy.md]\n---\n\n옛 내용', encoding='utf-8')
    other = concepts/'unrelated.md'
    other.write_text('---\nsources: [raw/notes/other.md]\n---\n\n다른 사용자의 내용', encoding='utf-8')
    ingest.save_state({'processed': ['raw/notes/legacy.md']})
    compile_now(monkeypatch, '--recompile')
    assert '새 내용' in page.read_text()
    assert '옛 내용' not in page.read_text()
    assert '다른 사용자의 내용' in other.read_text()
    assert len(list(concepts.glob('*.md'))) == 2
    raw.write_text('# 다시 수정\n\n다음 내용', encoding='utf-8')
    assert raw in ingest.find_unprocessed()


def test_recompile_dry_run_does_not_call_llm_or_rewrite_files(brain, monkeypatch):
    raw = brain/'raw/notes/a.md'
    raw.write_text('메모', encoding='utf-8')
    compile_now(monkeypatch)
    before = {p.relative_to(brain): p.read_bytes() for p in brain.rglob('*') if p.is_file()}
    monkeypatch.setenv('EDU_TEST_KEY', 'synthetic-no-network')
    async def forbidden(*args):
        pytest.fail('대상 확인만 하는 명령은 외부 호출을 하면 안 된다')
    monkeypatch.setattr(compiler, '_page_by_llm', forbidden)
    compile_now(monkeypatch, '--recompile', '--dry-run')
    assert before == {p.relative_to(brain): p.read_bytes() for p in brain.rglob('*') if p.is_file()}


@pytest.mark.parametrize('text', ['190010112345670', '12345678901234567890'])
def test_pii_does_not_extract_a_shorter_id_from_long_order_numbers(text):
    assert find_pii(text) == []
