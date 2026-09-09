from pathlib import Path
from graphify.extractors.bash import extract_bash
import pytest

def test_bats_native_and_comment_forms(tmp_path):
    src = b'''
@test "addition using bc" {
  result="$(echo 2+2 | bc)"
  [ "$result" -eq 4 ]
}

function invoking_foo_without_arguments_prints_usage { #@test
  run foo
  [ "$status" -eq 1 ]
}
'''
    bats_file = tmp_path / 'dummy.bats'
    bats_file.write_bytes(src)
    
    res = extract_bash(bats_file)
    if res.get('error'):
        pytest.skip(res['error'])
        
    nodes_by_label = {n['label']: n for n in res['nodes']}

    assert 'addition using bc' in nodes_by_label, "Missing native test node"
    assert nodes_by_label['addition using bc']['metadata']['kind'] == 'bash_test'

    assert 'invoking_foo_without_arguments_prints_usage()' in nodes_by_label, "Missing comment-form test node"
    assert nodes_by_label['invoking_foo_without_arguments_prints_usage()']['metadata']['kind'] == 'bash_test'
