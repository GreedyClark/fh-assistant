from functools import wraps

from django.conf import settings
from django.core import signing
from django.shortcuts import render
from init_data_py import validate_by_hash
from init_data_py.errors import InitDataPyError

TOKEN_SALT = "miniapp"
TOKEN_MAX_AGE = 12 * 3600
INIT_DATA_MAX_AGE = 24 * 3600


def user_from_init_data(init_data: str) -> int | None:
    try:
        data = validate_by_hash(init_data, settings.BOT.bot_token.get_secret_value(), expires_in=INIT_DATA_MAX_AGE)
    except (InitDataPyError, ValueError):
        return None
    if data.user is None or data.user.id != settings.BOT.allowed_user_id:
        return None
    return data.user.id


def make_token(user_id: int) -> str:
    return signing.TimestampSigner(salt=TOKEN_SALT).sign(str(user_id))


def token_valid(token: str | None) -> bool:
    if not token:
        return False
    try:
        value = signing.TimestampSigner(salt=TOKEN_SALT).unsign(token, max_age=TOKEN_MAX_AGE)
    except signing.BadSignature:
        return False
    return value == str(settings.BOT.allowed_user_id)


def require_token(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        token = request.POST.get("t") or request.GET.get("t")
        if not token_valid(token):
            return render(request, "dashboard/entry.html", {"next": request.path}, status=401)
        request.token = token
        return view(request, *args, **kwargs)

    return wrapper
