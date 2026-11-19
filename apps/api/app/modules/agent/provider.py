"""可替换的 Chat Completions 工具调用适配器；不开启时不创建网络客户端。"""
import json
import time
from urllib.parse import urlsplit

import httpx

from app.core.errors import ApiError


def ready(settings):
    try:
        url = urlsplit(settings.agent_base_url)
    except ValueError:
        return False
    return bool(settings.agent_provider == 'OPENAI_COMPATIBLE' and settings.agent_model.strip()
                and settings.agent_api_key.get_secret_value().strip() and url.scheme in ('http', 'https')
                and url.hostname and not url.username and not url.password and not url.query and not url.fragment)


def status(settings):
    enabled = ready(settings)
    return {'enabled': enabled, 'provider': settings.agent_provider,
            'message': '模型配置已启用，生成报告时将核对接口响应。' if enabled else '报告助手暂未启用，原有统计查询仍可使用。'}


def create_client(timeout):
    return httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False)


def complete(settings, messages, tools, deadline):
    if not ready(settings):
        raise ApiError(503, 'AGENT_UNAVAILABLE', '报告助手暂未启用，原有统计查询仍可使用。', {})
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ApiError(504, 'AGENT_TIMEOUT', '助手执行超时，请稍后重试。', {})
    body = {'model': settings.agent_model, 'messages': messages, 'tools': tools,
            'tool_choice': 'auto', 'max_tokens': settings.agent_max_output_tokens}
    try:
        with create_client(min(settings.agent_timeout_seconds, remaining)) as client:
            with client.stream('POST', settings.agent_base_url.rstrip('/') + '/chat/completions',
                               headers={'Authorization': 'Bearer ' + settings.agent_api_key.get_secret_value()}, json=body) as response:
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if time.monotonic() >= deadline:
                        raise ApiError(504, 'AGENT_TIMEOUT', '助手执行超时，请稍后重试。', {})
                    if size > settings.agent_max_response_bytes:
                        raise ValueError('response limit')
                    chunks.append(chunk)
        data = json.loads(b''.join(chunks))
        message = data['choices'][0]['message']
        if not isinstance(message, dict):
            raise ValueError('invalid message')
        return message
    except httpx.TimeoutException:
        raise ApiError(504, 'AGENT_TIMEOUT', '模型响应超时，原有统计查询仍可使用。', {}) from None
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        # 不回显响应正文、网络异常、地址或请求头，防止泄露凭据。
        raise ApiError(502, 'AGENT_MODEL_ERROR', '模型接口未返回有效结果，请检查获准接口配置。', {}) from None
