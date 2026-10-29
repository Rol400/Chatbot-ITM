def account_notice(request):
    """Aviso de una sola vez (por ejemplo, "guardamos tu correo")."""
    session = getattr(request, "session", None)
    notice = session.pop("account_notice", None) if session is not None else None
    return {"account_notice": notice}
