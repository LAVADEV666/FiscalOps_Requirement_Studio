from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
def test_all_editor_tabs_have_panels():
 html=(ROOT/'static/audit.html').read_text(encoding='utf-8');js=(ROOT/'static/audit.js').read_text(encoding='utf-8')
 tabs=set(re.findall(r'data-tab="([a-z]+)"',html));panels=set(re.findall(r'id="([a-z]+)Tab"',html))
 assert tabs<=panels, f'Pestañas sin panel: {sorted(tabs-panels)}'
 assert tabs == {'requirements','preview','visuals','metadata','templates'}
 assert tabs == panels
def test_templates_are_available_from_home_and_workspace():
 home=(ROOT/'static/index.html').read_text(encoding='utf-8')
 audit=(ROOT/'static/audit.html').read_text(encoding='utf-8')
 assert 'data-template-library' in home
 assert 'id="exportTemplate"' in audit
 assert all('/static/templates.js' in html for html in (home,audit))
def test_cache_buster_matches_release():
 html=(ROOT/'static/audit.html').read_text(encoding='utf-8');assert 'audit.js?v=8.0.1' in html and 'audit.css?v=8.0.1' in html
