import logging
from functools import wraps
from pathlib import Path

from flask import Flask, Response, g, jsonify, redirect, request, send_file, send_from_directory

from .audio import DEFAULT_QUALITY, UNSAFE_FILE_CHARACTERS, quality_choices
from .auth import SESSION_COOKIE, SESSION_SECONDS, AuthError, BuiltinAuth
from .config import Settings
from .jobs import JobError, JobStore
from .site_settings import SiteSettings, SiteSettingsError
from .sources import SourceError, resolve_any
from .tracks import Collection
from .worker import Worker
from .youtube import YouTube
from .zipstream import attachment_names, stream_zip

STATIC_DIR = Path(__file__).resolve().parent / "static"
CLIENT_HEADER = "X-SpotMP3"
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_LINK_LENGTH = 2048
MAX_ZIP_NAME_LENGTH = 100
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
CONTENT_SECURITY_POLICY = "; ".join((
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "font-src 'self'",
    "img-src 'self' data: https://*.scdn.co https://*.spotifycdn.com https://i.ytimg.com",
    "connect-src 'self' https://accounts.spotify.com https://api.spotify.com",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "form-action 'self'",
))

log = logging.getLogger("spotmp3.web")


def _error(message: str, status: int):
    return jsonify({"error": message}), status


def _collection_json(collection: Collection) -> dict:
    return {"kind": collection.kind, "name": collection.name, "truncated": collection.truncated,
            "tracks": [track.to_json() for track in collection.tracks]}


def _body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise JobError("send a JSON object")
    return data


def create_app(settings: Settings, auth, jobs: JobStore, worker: Worker, youtube: YouTube, site_settings: SiteSettings, resolver=resolve_any) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
    is_builtin = isinstance(auth, BuiltinAuth)
    signin_path = "/signin" if is_builtin else settings.starfire_signin_path

    def current_user():
        if "user" not in g:
            g.user = auth.current_user(request.cookies.get(SESSION_COOKIE), request.headers.get("Cookie"))
        return g.user

    def signed_in(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if current_user() is None:
                return _error("sign in first", 401)
            return view(*args, **kwargs)
        return wrapper

    def admin_only(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user = current_user()
            if user is None:
                return _error("sign in first", 401)
            if not user.is_admin:
                return _error("only an admin can change this", 403)
            return view(*args, **kwargs)
        return wrapper

    def accounts_admin_only(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not is_builtin:
                return _error("accounts are managed by the main sign-in service here", 403)
            return admin_only(view)(*args, **kwargs)
        return wrapper

    def set_session(response: Response, token: str) -> Response:
        response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_SECONDS, httponly=True, samesite="Lax", secure=settings.secure_cookies, path="/")
        return response

    @app.before_request
    def require_client_header():
        writes_api = request.method not in SAFE_METHODS and request.path.startswith("/api/")
        if writes_api and request.headers.get(CLIENT_HEADER) != "1":
            return _error("missing client header", 403)
        return None

    @app.after_request
    def add_security_headers(response: Response) -> Response:
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(AuthError)
    def auth_failed(error: AuthError):
        return _error(str(error), error.status)

    @app.errorhandler(JobError)
    def job_failed(error: JobError):
        return _error(str(error), error.status)

    @app.errorhandler(SiteSettingsError)
    def settings_rejected(error: SiteSettingsError):
        return _error(str(error), 400)

    @app.errorhandler(413)
    def too_large(_error_value):
        return _error("that request is too large", 413)

    def page(name: str):
        return send_from_directory(STATIC_DIR, name, max_age=0)

    @app.get("/")
    def index():
        if is_builtin and auth.needs_setup():
            return redirect("/setup")
        if current_user() is None:
            return redirect(signin_path)
        return page("index.html")

    @app.get("/setup")
    def setup_page():
        if not is_builtin or not auth.needs_setup():
            return redirect("/")
        return page("setup.html")

    @app.get("/signin")
    def signin_page():
        if not is_builtin:
            return redirect(signin_path)
        if auth.needs_setup():
            return redirect("/setup")
        return page("signin.html")

    @app.get("/spotify/callback")
    def spotify_callback():
        return page("callback.html")

    @app.get("/static/<path:name>")
    def static_file(name: str):
        return send_from_directory(STATIC_DIR, name, max_age=3600)

    @app.get("/api/session")
    def session_state():
        user = current_user()
        return jsonify({"mode": auth.mode, "needsSetup": auth.needs_setup(), "user": user.to_json() if user else None})

    @app.post("/api/setup")
    def setup():
        if not is_builtin:
            return _error("setup is only used with built-in accounts", 404)
        data = _body()
        token = auth.create_first_admin(data.get("email"), data.get("password"), data.get("confirm"))
        return set_session(jsonify({"ok": True}), token)

    @app.post("/api/signin")
    def signin():
        if not is_builtin:
            return _error("sign in through the main sign-in page", 404)
        data = _body()
        token = auth.sign_in(data.get("email"), data.get("password"), request.remote_addr or "unknown")
        return set_session(jsonify({"ok": True}), token)

    @app.post("/api/signout")
    def signout():
        if is_builtin:
            auth.sign_out(request.cookies.get(SESSION_COOKIE))
        response = jsonify({"ok": True})
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.get("/api/config")
    @signed_in
    def config():
        return jsonify({
            "user": current_user().to_json(),
            "mode": auth.mode,
            "canSignOut": is_builtin,
            "canManageAccounts": is_builtin and current_user().is_admin,
            "canManageSettings": current_user().is_admin,
            "qualities": [{"key": key, "label": label} for key, label in quality_choices()],
            "defaultQuality": DEFAULT_QUALITY,
            "maxTracks": settings.max_tracks_per_job,
            "retentionHours": settings.retention_hours,
            "spotifyClientId": site_settings.spotify_client_id(),
            "spotifyRedirectUri": site_settings.redirect_uri(request.url_root),
        })

    @app.get("/api/settings")
    @admin_only
    def read_site_settings():
        return jsonify(site_settings.to_json(request.url_root))

    @app.put("/api/settings")
    @admin_only
    def save_site_settings():
        data = _body()
        site_settings.update(data.get("spotifyClientId"), data.get("publicUrl"))
        return jsonify(site_settings.to_json(request.url_root))

    @app.get("/api/accounts")
    @accounts_admin_only
    def list_accounts():
        return jsonify({"accounts": auth.list_accounts()})

    @app.post("/api/accounts")
    @accounts_admin_only
    def add_account():
        data = _body()
        return jsonify(auth.add_account(data.get("email"), data.get("password"), data.get("confirm"), data.get("isAdmin") is True)), 201

    @app.delete("/api/accounts/<int:account_id>")
    @accounts_admin_only
    def delete_account(account_id: int):
        owner = auth.delete_account(account_id, current_user())
        jobs.delete_owner(owner)
        worker.cleanup()
        return jsonify({"ok": True})

    @app.post("/api/resolve")
    @signed_in
    def resolve():
        link = _body().get("link")
        if not isinstance(link, str) or not link.strip() or len(link) > MAX_LINK_LENGTH:
            return _error("paste a Spotify or YouTube link", 400)
        try:
            collection = resolver(link.strip(), youtube, settings.max_tracks_per_job)
        except SourceError as error:
            return _error(str(error), 400)
        except OSError as error:
            log.warning("reading %r failed: %s", link, error)
            return _error("that link could not be read right now, try again in a moment", 502)
        return jsonify(_collection_json(collection))

    @app.get("/api/jobs")
    @signed_in
    def list_jobs():
        return jsonify({"jobs": jobs.list_for(current_user().owner_key)})

    @app.post("/api/jobs")
    @signed_in
    def create_job():
        if not worker.has_free_space():
            return _error("the server is low on disk space, try again later", 507)
        data = _body()
        job_id = jobs.create(current_user().owner_key, data.get("name"), data.get("quality"), data.get("tracks"))
        worker.notify()
        return jsonify({"id": job_id}), 201

    @app.get("/api/jobs/<int:job_id>")
    @signed_in
    def job_detail(job_id: int):
        return jsonify(jobs.detail(current_user().owner_key, job_id))

    @app.post("/api/jobs/<int:job_id>/cancel")
    @signed_in
    def cancel_job(job_id: int):
        jobs.cancel(current_user().owner_key, job_id)
        return jsonify({"ok": True})

    @app.delete("/api/jobs/<int:job_id>")
    @signed_in
    def delete_job(job_id: int):
        jobs.delete(current_user().owner_key, job_id)
        worker.cleanup()
        return jsonify({"ok": True})

    @app.post("/api/items/<int:item_id>/retry")
    @signed_in
    def retry_item(item_id: int):
        jobs.retry(current_user().owner_key, item_id)
        worker.notify()
        return jsonify({"ok": True})

    @app.get("/api/items/<int:item_id>/file")
    @signed_in
    def item_file(item_id: int):
        relative_path, file_name = jobs.item_file(current_user().owner_key, item_id)
        path = worker.file_for(relative_path)
        if path is None:
            return _error("that file has been cleaned up", 410)
        return send_file(path, mimetype="audio/mpeg", as_attachment=True, download_name=file_name)

    @app.get("/api/jobs/<int:job_id>/zip")
    @signed_in
    def job_zip(job_id: int):
        name, files = jobs.job_files(current_user().owner_key, job_id)
        entries = [(path, file_name) for path, file_name in ((worker.file_for(relative), file_name) for relative, file_name in files) if path]
        zip_name = UNSAFE_FILE_CHARACTERS.sub("", name).strip(" .")[:MAX_ZIP_NAME_LENGTH] or "SpotMP3"
        response = Response(stream_zip(entries), mimetype="application/zip")
        response.headers.set("Content-Disposition", "attachment", **attachment_names(f"{zip_name}.zip"))
        return response

    return app
