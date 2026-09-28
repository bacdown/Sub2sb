import io
import unittest
from unittest.mock import MagicMock, patch

from sub2singbox import PROJECT_ROOT, get_subscription, prompt_interactive_args, source_label


class InteractiveCliTests(unittest.TestCase):
    def test_menu_collects_multiple_sources_and_default_template(self):
        answers = [
            "./first.yaml",
            "https://subscriptions.example/sub",
            "",
            "",
            "",
        ]
        with patch("builtins.input", side_effect=answers), patch("sys.stdout", new_callable=io.StringIO):
            args = prompt_interactive_args()

        self.assertEqual(args.subscription, ["./first.yaml", "https://subscriptions.example/sub"])
        self.assertEqual(
            args.config,
            str(PROJECT_ROOT / "templates" / "config_phone.json"),
        )
        self.assertIsNone(args.output)

    def test_menu_accepts_custom_template_and_output_path(self):
        answers = ["./subscription.yaml", "", "4", "./custom.json", "./result.json"]
        with patch("builtins.input", side_effect=answers), patch("sys.stdout", new_callable=io.StringIO):
            args = prompt_interactive_args()

        self.assertEqual(args.subscription, ["./subscription.yaml"])
        self.assertEqual(args.config, "./custom.json")
        self.assertEqual(args.output, "./result.json")

    def test_download_rejects_unrecognized_response_without_echoing_body(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"<!doctype html><title>Sign in</title>"
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        url = "https://subscriptions.example/?token=top-secret"

        with patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(ValueError) as error:
                get_subscription(url)

        self.assertIn("Content-Type: text/html", str(error.exception))
        self.assertIn("37 字节", str(error.exception))
        self.assertNotIn("Sign in", str(error.exception))
        self.assertNotIn("top-secret", str(error.exception))

    def test_remote_source_label_hides_path_and_query_credentials(self):
        self.assertEqual(
            source_label("https://subscriptions.example/secret/path?token=top-secret"),
            "https://subscriptions.example",
        )


if __name__ == "__main__":
    unittest.main()
