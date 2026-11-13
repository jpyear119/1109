"""PC-specific prompt must remain compatible with the reviewed Task XML exporter."""
from claude_vision import schema_d, schema_pc


def test_pc_schema_blocks_parallel_without_changing_research_d():
    d_types = schema_d.BT_SCHEMA_D["definitions"]["node"]["properties"]["type"]["enum"]
    pc_types = schema_pc.BT_SCHEMA_PC_D["definitions"]["node"]["properties"]["type"]["enum"]
    assert "Parallel" in d_types
    assert "Parallel" not in pc_types


def test_pc_prompt_explains_fallback_success_semantics():
    prompt = schema_pc.render_prompt_pc_d(
        "PC1", 0.0, 10.0,
        [{"order": 1, "timestamp_s": 5.0, "file": "0001.jpg"}],
        "Step 1: inspect device",
    )
    assert "first child returning SUCCESS" in prompt
    assert "Parallel" not in schema_pc.schema_bundle_pc_d()["node_types"]
