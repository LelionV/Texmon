"""
Thread-local "current user" tracking.

Model.save() has no access to the current request, but AuditModel needs to
stamp created_by/updated_by automatically wherever possible (e.g. from
model-level signals or service-layer code that doesn't want to thread a
`user` argument through every call). This middleware stashes the
authenticated user in a thread-local at the start of each request so
core.utils.get_current_user() can retrieve it.

This is a convenience fallback only -- views/services that already have
`request.user` should still pass it explicitly to service functions rather
than relying on this implicitly. Explicit is safer for testing and for
management-command / background-job contexts where there is no request.
"""

import threading

_thread_locals = threading.local()


def get_current_user():
    return getattr(_thread_locals, "user", None)


class CurrentUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _thread_locals.user = getattr(request, "user", None)
        try:
            response = self.get_response(request)
        finally:
            _thread_locals.user = None
        return response
