import io
import unittest
from urllib.error import HTTPError

from football_agents.llm.client import QwenClient


class QwenClientTests(unittest.TestCase):
    def test_format_http_error_includes_dashscope_code_and_request_id(self):
        body = (
            '{"error":{"message":"The free quota has been exhausted.",'
            '"type":"AllocationQuota.FreeTierOnly","code":"AllocationQuota.FreeTierOnly"},'
            '"request_id":"req-123"}'
        ).encode("utf-8")
        error = HTTPError(
            url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=io.BytesIO(body),
        )

        message = QwenClient._format_http_error(error)

        self.assertIn("Qwen API HTTP 403", message)
        self.assertIn("AllocationQuota.FreeTierOnly", message)
        self.assertIn("The free quota has been exhausted.", message)
        self.assertIn("request_id=req-123", message)


if __name__ == "__main__":
    unittest.main()
