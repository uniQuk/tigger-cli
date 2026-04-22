from newcli.types import Message, ToolCallRecord
from newcli.provider import messages_to_openai, openai_tool_calls_to_records

def test_messages_to_openai_user():
    msgs = [Message(role="user", content="hello")]
    result = messages_to_openai(msgs)
    assert result == [{"role": "user", "content": "hello"}]

def test_messages_to_openai_tool():
    m = Message(role="tool", content="result", tool_call_id="c1", name="read")
    result = messages_to_openai([m])
    assert result[0]["role"] == "tool"
    assert result[0]["tool_call_id"] == "c1"

def test_messages_to_openai_assistant_with_tool_calls():
    tc = ToolCallRecord(call_id="c1", name="read", args={"path": "/x"})
    m = Message(role="assistant", content="", tool_calls=[tc])
    result = messages_to_openai([m])
    assert result[0]["tool_calls"][0]["function"]["name"] == "read"

def test_openai_tool_calls_to_records():
    raw = [{
        "id": "c1",
        "function": {"name": "read", "arguments": '{"path": "/x"}'},
    }]
    records = openai_tool_calls_to_records(raw)
    assert len(records) == 1
    assert records[0].name == "read"
    assert records[0].args == {"path": "/x"}

def test_openai_tool_calls_malformed_json():
    raw = [{"id": "c1", "function": {"name": "read", "arguments": "{bad json"}}]
    records = openai_tool_calls_to_records(raw)
    assert records[0].args == {}
