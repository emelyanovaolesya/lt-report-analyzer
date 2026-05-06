import unittest

from app.services.security import get_password_hash, verify_password


class SecurityServiceTests(unittest.TestCase):
    def test_password_hash_is_not_equal_to_plain_text(self) -> None:
        password = "admin123"

        hashed = get_password_hash(password)

        self.assertNotEqual(password, hashed)

    def test_verify_password_returns_true_for_valid_password(self) -> None:
        password = "strong-password"
        hashed = get_password_hash(password)

        self.assertTrue(verify_password(password, hashed))

    def test_verify_password_returns_false_for_invalid_password(self) -> None:
        hashed = get_password_hash("correct-password")

        self.assertFalse(verify_password("wrong-password", hashed))


if __name__ == "__main__":
    unittest.main()
