from app.middleware.auth_stub import AuthIdentity, AuthStubMiddleware
from app.middleware.errors import install_error_handlers
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_body_limit import RequestBodyLimitMiddleware
from app.middleware.security import (
    SecurityHeadersMiddleware,
    configure_cors,
    configure_trusted_hosts,
)
from app.middleware.upload_guard import UploadGuardMiddleware

__all__ = [
    "AuthIdentity",
    "AuthStubMiddleware",
    "RateLimitMiddleware",
    "RequestBodyLimitMiddleware",
    "SecurityHeadersMiddleware",
    "UploadGuardMiddleware",
    "configure_cors",
    "configure_trusted_hosts",
    "install_error_handlers",
]
