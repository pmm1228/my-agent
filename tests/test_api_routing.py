import unittest

from app.api.main import create_app


class ApiRoutingTests(unittest.TestCase):
    def test_public_api_operations_are_registered(self):
        schema = create_app().openapi()
        operations = {
            (method.upper(), path)
            for path, path_item in schema["paths"].items()
            for method in path_item
            if method in {"get", "post", "patch", "delete"}
        }

        self.assertEqual(
            operations,
            {
                ("GET", "/health"),
                ("POST", "/auth/login"),
                ("POST", "/chat"),
                ("POST", "/chat/confirm"),
                ("POST", "/chat/stream"),
                ("GET", "/chat/sessions"),
                ("GET", "/chat/sessions/{thread_id}/messages"),
                ("DELETE", "/chat/sessions/{thread_id}"),
                ("POST", "/users"),
                ("GET", "/users"),
                ("GET", "/users/{user_id}"),
                ("PATCH", "/users/{user_id}"),
                ("DELETE", "/users/{user_id}"),
                ("GET", "/me"),
            },
        )

    def test_public_api_schema_components_are_registered(self):
        schemas = create_app().openapi()["components"]["schemas"]

        self.assertEqual(
            set(schemas),
            {
                "ChatConfirmationRequest",
                "ChatMessageListResponse",
                "ChatMessageResponse",
                "ChatRequest",
                "ChatResponse",
                "ChatSessionDeleteResponse",
                "ChatSessionListResponse",
                "ChatSessionResponse",
                "HTTPValidationError",
                "HealthResponse",
                "LoginRequest",
                "LoginResponse",
                "UpdateUserRequest",
                "UpdateUserResponse",
                "UserCreateRequest",
                "UserCreateResponse",
                "UserDeleteResponse",
                "UserListResponse",
                "UserResponse",
                "ValidationError",
            },
        )


if __name__ == "__main__":
    unittest.main()
