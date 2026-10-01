import json

from app.compliance.failures import is_azure_jailbreak_block


def test_jailbreak_classification_requires_an_explicit_azure_block() -> None:
    body = json.dumps(
        [
            {
                "kind": "response",
                "provider_name": "azure",
                "finish_reason": "content_filter",
                "provider_details": {
                    "finish_reason": "content_filter",
                    "content_filter_result": {"jailbreak": {"detected": True, "filtered": True}},
                },
            }
        ]
    )
    assert is_azure_jailbreak_block(body)

    non_azure_response = json.loads(body)
    non_azure_response[0]["provider_name"] = "openai"
    assert not is_azure_jailbreak_block(json.dumps(non_azure_response))

    not_detected = json.loads(body)
    not_detected[0]["provider_details"]["content_filter_result"]["jailbreak"]["detected"] = False
    assert not is_azure_jailbreak_block(json.dumps(not_detected))

    not_filtered = json.loads(body)
    not_filtered[0]["provider_details"]["content_filter_result"]["jailbreak"]["filtered"] = False
    assert not is_azure_jailbreak_block(json.dumps(not_filtered))

    other_category = json.loads(body)
    other_category[0]["provider_details"]["content_filter_result"] = {
        "hate": {"detected": True, "filtered": True}
    }
    assert not is_azure_jailbreak_block(json.dumps(other_category))
    assert not is_azure_jailbreak_block("content_filter jailbreak filtered")
