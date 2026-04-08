from flask import flash, jsonify, redirect, request, url_for


def is_json_request():
    if request.headers.get("X-Requested-With", "").lower() == "xmlhttprequest":
        return True
    if request.is_json:
        return True
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return best == "application/json" and request.accept_mimetypes[best] > request.accept_mimetypes["text/html"]


def is_xhr_request():
    return is_json_request()


def build_json_payload(ok, message="", category=None, **payload):
    body = {
        "ok": bool(ok),
        "message": str(message or ""),
    }
    if category:
        body["category"] = category
    body.update(payload)
    if not ok:
        body.setdefault("error", body["message"])
    return body


def json_success(message="", status_code=200, category="success", **payload):
    return jsonify(build_json_payload(True, message, category, **payload)), status_code


def json_error(message, status_code=400, category="error", **payload):
    return jsonify(build_json_payload(False, message, category, **payload)), status_code


def route_response(endpoint, ok, message, category="success", status_code=200, redirect_values=None, **payload):
    if is_json_request():
        if ok:
            return json_success(message, status_code=status_code, category=category, **payload)
        return json_error(message, status_code=status_code, category=category, **payload)
    flash(str(message or ""), category)
    return redirect(url_for(endpoint, **(redirect_values or {})))


def library_action_response(ok, message, category="success", status_code=200, **payload):
    return route_response("library", ok, message, category, status_code, **payload)


def album_editor_response(album_id, ok, message, category="success", status_code=200, **payload):
    return route_response(
        "library_album",
        ok,
        message,
        category,
        status_code,
        redirect_values={"album_id": album_id},
        **payload,
    )
