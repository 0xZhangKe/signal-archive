import copy
import json
import time
import unittest
import urllib.error
from unittest.mock import patch

from scripts.ai_agent import AgentSettings, ApiError, ResearchAgent, post_json, validate_items


NOW = "2026-09-23T10:00:00Z"
URL = "https://example.com/release"
ITEM = {
    "title": "版本发布", "url": URL, "publishedAt": "2026-09-23T08:00:00Z",
    "summary": "新增工具调用能力。", "keyPoints": ["支持检索工具"],
    "references": [{"title": "官方说明", "url": URL}],
}


def reply(content=None, calls=None, finish="stop"):
    message = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = calls
    return {"choices": [{"message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


def call(name, arguments, identifier="call1"):
    return {"id": identifier, "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}


class FakeApi:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def __call__(self, url, key, payload, timeout):
        self.requests.append((url, key, copy.deepcopy(payload), timeout))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


class AiAgentTest(unittest.TestCase):
    def test_search_extract_and_structured_output_protocol(self):
        api = FakeApi([
            reply(calls=[call("search_web", {"query": "official releases", "time_range": "week"})]),
            {"results": [{"title": "Release", "url": URL, "content": "Search evidence"}], "usage": {"credits": 1}},
            reply(calls=[call("fetch_pages", {"urls": [URL]}, "call2")]),
            {"results": [{"url": URL, "raw_content": "Full announcement"}]},
            reply("Enough evidence"),
            reply(json.dumps({"items": [ITEM]})),
        ])
        agent = ResearchAgent("router-secret", "tavily-secret", request=api)
        self.assertEqual([ITEM], agent.run("中文开发动态", now=NOW, last_success=None, recent=[]))
        self.assertEqual("https://api.tavily.com/search", api.requests[1][0])
        self.assertEqual("tavily-secret", api.requests[1][1])
        self.assertEqual("https://api.tavily.com/extract", api.requests[3][0])
        final = api.requests[-1][2]
        self.assertEqual("none", final["tool_choice"])
        self.assertEqual(2, len(final["tools"]))
        self.assertTrue(final["response_format"]["json_schema"]["strict"])
        self.assertTrue(final["provider"]["require_parameters"])
        self.assertEqual(["call1", "call2"], [m["tool_call_id"] for m in final["messages"] if m["role"] == "tool"])
        self.assertNotIn("secret", json.dumps(final))
        self.assertEqual(40, agent.usage["prompt_tokens"])
        self.assertEqual(1, agent.usage["credits"])

    def test_invalid_final_json_is_corrected_once(self):
        api = FakeApi([
            reply(calls=[call("search_web", {"query": "updates"})]), {"results": []},
            reply("done"), reply("invalid JSON"), reply('{"items": []}'),
        ])
        agent = ResearchAgent("a", "b", request=api)
        self.assertEqual([], agent.run("updates", now=NOW, last_success=None, recent=[]))
        self.assertIn("Fix this validation", api.requests[-1][2]["messages"][-1]["content"])

    def test_unobserved_citation_fails_even_if_model_repeats_it(self):
        api = FakeApi([
            reply(calls=[call("search_web", {"query": "updates"})]), {"results": []},
            reply("done"), reply(json.dumps({"items": [ITEM]})), reply(json.dumps({"items": [ITEM]})),
        ])
        with self.assertRaisesRegex(ValueError, "after correction"):
            ResearchAgent("a", "b", request=api).run("updates", now=NOW, last_success=None, recent=[])

    def test_failed_search_is_not_a_successful_empty_run(self):
        api = FakeApi([
            reply(calls=[call("search_web", {"query": "updates"})]), ApiError("API HTTP 401"), reply("done"),
        ])
        with self.assertRaisesRegex(ApiError, "no web search succeeded"):
            ResearchAgent("a", "b", request=api).run("updates", now=NOW, last_success=None, recent=[])

    def test_rejects_unobserved_extract_url_without_requesting_it(self):
        agent = ResearchAgent("a", "b", request=lambda *args: self.fail("unexpected request"))
        with self.assertRaisesRegex(ValueError, "search results"):
            agent.extract({"urls": ["https://example.com/unknown"]})

    def test_tool_loop_is_bounded(self):
        api = FakeApi([
            reply(calls=[call("search_web", {"query": "updates"})]), {"results": []},
            reply('{"items": []}'),
        ])
        agent = ResearchAgent("a", "b", request=api, settings=AgentSettings(max_tool_calls=1))
        self.assertEqual([], agent.run("updates", now=NOW, last_success=None, recent=[]))
        self.assertEqual(3, len(api.requests))
        self.assertEqual("none", api.requests[-1][2]["tool_choice"])

    def test_total_deadline_prevents_network_request(self):
        agent = ResearchAgent("a", "b", request=lambda *args: self.fail("unexpected request"),
                              settings=AgentSettings(timeout=0))
        with self.assertRaisesRegex(ApiError, "time budget"):
            agent.run("updates", now=NOW, last_success=None, recent=[])

    def test_transient_api_errors_retry_but_auth_errors_do_not(self):
        api = FakeApi([ApiError("API HTTP 429", retryable=True), {"results": []}])
        agent = ResearchAgent("a", "b", request=api)
        agent.deadline = time.monotonic() + 30
        with patch("scripts.ai_agent.time.sleep"):
            self.assertEqual({"results": []}, agent.api("https://example.com", "a", {}))
        self.assertEqual(2, len(api.requests))
        api = FakeApi([ApiError("API HTTP 401")])
        agent.request = api
        with self.assertRaises(ApiError):
            agent.api("https://example.com", "a", {})
        self.assertEqual(1, len(api.requests))

    def test_http_errors_do_not_expose_response_body_or_key(self):
        error = urllib.error.HTTPError("https://example.com", 401, "secret echoed by API", {}, None)
        with patch("scripts.ai_agent.urllib.request.build_opener") as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaisesRegex(ApiError, "^API HTTP 401$"):
                post_json("https://example.com", "very-secret", {}, 5)

    def test_rejects_truncated_response(self):
        api = FakeApi([reply("partial", finish="length")])
        with self.assertRaisesRegex(ApiError, "truncated"):
            ResearchAgent("a", "b", request=api).run("updates", now=NOW, last_success=None, recent=[])

    def test_validates_dates_and_references(self):
        for published in ("2026-09-23", "2028-01-01T00:00:00Z", "not a date"):
            with self.subTest(published=published), self.assertRaises(ValueError):
                validate_items({"items": [{**ITEM, "publishedAt": published}]}, {URL}, NOW)
        unknown_date = {**ITEM, "publishedAt": None}
        self.assertIsNone(validate_items({"items": [unknown_date]}, {URL}, NOW)[0]["publishedAt"])
        with self.assertRaisesRegex(ValueError, "reference URL"):
            validate_items({"items": [{**ITEM, "references": [{"title": "Invented", "url": "https://example.com/fake"}]}]}, {URL}, NOW)


if __name__ == "__main__":
    unittest.main()
