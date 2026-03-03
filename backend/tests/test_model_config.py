import unittest

from scripts.model_config import (
    DEFAULT_ALIGNMENT_MODEL_ALIAS,
    resolve_alignment_model,
    resolve_alignment_model_alias,
)


class AlignmentModelConfigTests(unittest.TestCase):
    def test_none_uses_sonnet_default(self) -> None:
        alias = resolve_alignment_model_alias(None)
        model = resolve_alignment_model(None)

        self.assertEqual(alias, DEFAULT_ALIGNMENT_MODEL_ALIAS)
        self.assertEqual(model, "claude-sonnet-4-6")

    def test_blank_or_whitespace_uses_sonnet_default(self) -> None:
        alias = resolve_alignment_model_alias("   ")
        model = resolve_alignment_model("  ")

        self.assertEqual(alias, "sonnet")
        self.assertEqual(model, "claude-sonnet-4-6")

    def test_haiku_alias_is_case_insensitive(self) -> None:
        alias = resolve_alignment_model_alias("HaIkU")
        model = resolve_alignment_model("HaIkU")

        self.assertEqual(alias, "haiku")
        self.assertEqual(model, "claude-haiku-4-5")

    def test_invalid_alias_raises_clear_error(self) -> None:
        with self.assertRaises(ValueError) as exc:
            resolve_alignment_model_alias("foo")

        message = str(exc.exception)
        self.assertIn("Invalid ALIGN_MODEL value", message)
        self.assertIn("Allowed values", message)
        self.assertIn("sonnet", message)
        self.assertIn("haiku", message)


if __name__ == "__main__":
    unittest.main()
