def dispatch(request):
    """Route an incoming request.

    Prose context: when the PaymentGateway is unavailable the request is
    queued for a later retry, and the TokenRefresher renews the caller's
    credentials before any retry is attempted.
    """
    return request
