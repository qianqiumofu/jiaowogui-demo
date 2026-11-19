import json
import time

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import ApiError
from app.modules.agent import provider


def settings(**extra):
    return Settings(_env_file=None, agent_provider='OPENAI_COMPATIBLE', agent_model='synth',
                    agent_base_url='https://models.invalid/v1', agent_api_key='synth-secret-only', **extra)


def transport(monkeypatch, handler):
    monkeypatch.setattr(provider, 'create_client', lambda timeout: httpx.Client(transport=httpx.MockTransport(handler)))


def test_compatible_adapter_sends_tools_and_reads_tool_calls(monkeypatch):
    def handle(request):
        assert str(request.url) == 'https://models.invalid/v1/chat/completions'
        assert request.headers['authorization'] == 'Bearer synth-secret-only'
        body = json.loads(request.content)
        assert body['model'] == 'synth' and body['tools'] == [{'type':'function'}]
        return httpx.Response(200, json={'choices':[{'message':{'tool_calls':[]}}]})

    transport(monkeypatch, handle)
    assert provider.complete(settings(), [], [{'type':'function'}], time.monotonic()+10) == {'tool_calls':[]}


@pytest.mark.parametrize('failure', ['timeout', 'http', 'json', 'oversize'])
def test_adapter_hides_credentials_and_provider_errors(monkeypatch, failure):
    def handle(request):
        if failure == 'timeout':
            raise httpx.ReadTimeout('synth-secret-only', request=request)
        if failure == 'http':
            return httpx.Response(401, text='synth-secret-only')
        if failure == 'oversize':
            return httpx.Response(200, content=b'x'*2048)
        return httpx.Response(200, text='synth-secret-only')

    transport(monkeypatch, handle)
    with pytest.raises(ApiError) as exc:
        provider.complete(settings(agent_max_response_bytes=1024), [], [], time.monotonic()+10)
    assert exc.value.code == ('AGENT_TIMEOUT' if failure == 'timeout' else 'AGENT_MODEL_ERROR')
    assert 'synth-secret-only' not in str(exc.value)


def test_invalid_or_incomplete_config_is_unavailable():
    config = settings()
    config.agent_base_url = 'http://[invalid'
    assert provider.status(config)['enabled'] is False
    config.agent_base_url = 'https://user:password@models.invalid/v1'
    assert provider.status(config)['enabled'] is False


def test_elapsed_deadline_never_creates_network_client(monkeypatch):
    monkeypatch.setattr(provider, 'create_client', lambda *a: pytest.fail('expired deadline attempted network'))
    with pytest.raises(ApiError) as exc:
        provider.complete(settings(), [], [], time.monotonic()-1)
    assert exc.value.code == 'AGENT_TIMEOUT'
