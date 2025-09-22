from urllib.parse import quote
from typing import Dict, Optional, Any

from os import getenv
from requests import get, post
from requests.exceptions import RequestException, HTTPError

from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

BASE_URL = getenv("BACKEND_API_URL", "http://localhost:8001")
SECURE_COOKIES = getenv("SECURE_COOKIES", "0") in ("1","true","True")

app = FastAPI()
templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/templates", StaticFiles(directory="templates"), name="templates")


def _build_auth_headers(request: Request) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    session_token = request.cookies.get("session_token")
    if session_token:
        headers["Cookie"] = f"session_token={session_token}"
    return headers


async def make_backend_request(
    request: Request,
    method: str,
    endpoint: str,
    data: Optional[Dict] = None,
    success_template: Optional[str] = None,
    error_template: Optional[str] = None,
    redirect_url_on_unauthorized: Optional[str] = "/directlogin",
    **template_args: Any,
):
    headers = _build_auth_headers(request)

    if not headers and redirect_url_on_unauthorized and endpoint not in ["/login", "/register"]:
        return RedirectResponse(url=redirect_url_on_unauthorized, status_code=302)

    try:
        if method.lower() == "post":
            resp = post(f"{BASE_URL}{endpoint}", json=data, headers=headers)
        elif method.lower() == "get":
            resp = get(f"{BASE_URL}{endpoint}", headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        resp.raise_for_status()
        payload = resp.json() if resp.content else {}
        merged = {**template_args, **payload}
        return (
            templates.TemplateResponse(success_template, {"request": request, **merged})
            if success_template
            else payload
        )

    except HTTPError as e:
        if e.response is not None and e.response.status_code == 401 and redirect_url_on_unauthorized:
            return RedirectResponse(url=f"{redirect_url_on_unauthorized}?message=Sessione scaduta", status_code=302)

        detail = "Si è verificato un errore durante la richiesta al backend."
        if e.response is not None:
            try:
                er = e.response.json()
                detail = er.get("detail") or er.get("message") or detail
            except Exception:
                detail = e.response.text or detail

        tmpl = error_template or success_template
        if tmpl:
            return templates.TemplateResponse(tmpl, {"request": request, "message": detail, **template_args})
        raise

    except RequestException as e:
        tmpl = error_template or success_template
        if tmpl:
            return templates.TemplateResponse(
                tmpl,
                {
                    "request": request,
                    "message": f"Impossibile connettersi al backend: {e}",
                    **template_args,
                },
            )
        raise


def _copy_backend_cookies_to(response_redirect: RedirectResponse, backend_response):
    for cookie_name, cookie_value in backend_response.cookies.items():
        response_redirect.set_cookie(
            key=cookie_name,
            value=cookie_value,
            httponly=True,
            samesite="lax",
            secure=SECURE_COOKIES,  # was True
            path="/",
        )


# --------------------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/directlogin", response_class=HTMLResponse)
def directlogin(request: Request, message: str = "", message_type: str = "success"):
    return templates.TemplateResponse("login.html", {"request": request, "message": message, "message_type": message_type})

@app.get("/directregister", response_class=HTMLResponse)
def directregister(request: Request, message: str = "", message_type: str = "success"):
    return templates.TemplateResponse("register.html", {"request": request, "message": message, "message_type": message_type})


@app.post("/login", response_class=HTMLResponse)
async def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    if not username.strip() or not password.strip():
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "message": "Username o password non validi.", "message_type": "danger"},
        )

    try:
        resp = post(f"{BASE_URL}/login", json={"username": username, "password": password})
        resp.raise_for_status()
    except HTTPError as e:
        detail = "Errore durante il login."
        if e.response is not None:
            try:
                detail = e.response.json().get("detail", detail)
            except Exception:
                detail = e.response.text or detail
        return templates.TemplateResponse("login.html", {"request": request, "message": detail, "message_type": "danger"})
    except RequestException as e:
        return templates.TemplateResponse("login.html", {"request": request, "message": f"Backend non raggiungibile: {e}", "message_type": "danger"})

    redirect = RedirectResponse(url="/profile", status_code=302)
    _copy_backend_cookies_to(redirect, resp)
    return redirect



@app.post("/register", response_class=HTMLResponse)
async def register_post(request: Request, username: str = Form(...), password: str = Form(...), repeatpass: str = Form(...)):
    if password != repeatpass:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "message": "Le password non coincidono.", "message_type": "danger"},
        )
    if not username.strip() or not password.strip():
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "message": "Dati non validi.", "message_type": "danger"},
        )

    # Chiama il backend manualmente (così puoi gestire i colori)
    try:
        resp = post(f"{BASE_URL}/register", json={"username": username, "password": password})
        resp.raise_for_status()
    except HTTPError as e:
        detail = "Registrazione fallita."
        if e.response is not None:
            try:
                detail = e.response.json().get("detail", detail)
            except Exception:
                detail = e.response.text or detail
        return templates.TemplateResponse("register.html", {"request": request, "message": detail, "message_type": "danger"})
    except RequestException as e:
        return templates.TemplateResponse("register.html", {"request": request, "message": f"Backend non raggiungibile: {e}", "message_type": "danger"})

    # Successo: torna alla pagina di login con messaggio verde
    return templates.TemplateResponse("login.html", {"request": request, "message": "Registrazione completata!", "message_type": "success"})



@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request, message: str = "", message_type: str = "success"):
    headers = _build_auth_headers(request)
    if not headers:
        return RedirectResponse(url="/directlogin?message=Sessione%20scaduta&message_type=danger", status_code=302)

    profile_data = await make_backend_request(
        request, "get", "/profile",
        success_template=None,
        error_template="login.html",
    )
    if isinstance(profile_data, RedirectResponse):
        return profile_data

    beers_data = await make_backend_request(
        request, "get", "/beers",
        success_template=None,
        error_template="login.html",
    )
    if isinstance(beers_data, RedirectResponse):
        return beers_data

    items = beers_data.get("items", [])
    for b in items:
        url = (b.get("image_url") or "")
        if url.startswith("/media/"):
            b["image_url"] = url.replace("/media/", "/bmedia/", 1)

    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "profile": profile_data,
            "beers": items,
            "message": message,
            "message_type": message_type,  # <-- QUI ora esiste
            "is_owner": True,
        },
    )



@app.post("/upload_beer", response_class=HTMLResponse)
async def upload_beer(request: Request, beer_name: str = Form(""), photo: UploadFile = File(...)):
    headers = _build_auth_headers(request)
    if not headers:
        return RedirectResponse(url="/directlogin?message=Sessione%20scaduta&message_type=danger", status_code=302)

    try:
        with photo.file as fp:
            files = {"photo": (photo.filename, fp, photo.content_type or "image/jpeg")}
            data = {"name": beer_name}
            resp = post(f"{BASE_URL}/beers/upload", headers=headers, files=files, data=data)
            resp.raise_for_status()
    except HTTPError as e:
        detail = "Upload fallito."
        if e.response is not None:
            try:
                detail = e.response.json().get("detail", detail)
            except Exception:
                detail = e.response.text or detail
        # ritorna errore con message_type rosso
        return await profile(request, message=detail, message_type="danger")
    except RequestException as e:
        return await profile(request, message=f"Backend non raggiungibile: {e}", message_type="danger")

    # successo: verde
    return RedirectResponse(url="/profile?message=Upload%20ok&message_type=success", status_code=302)




@app.post("/add_manual_beers", response_class=HTMLResponse)
async def add_manual_beers(request: Request, count: str = Form(""), name: str = Form("")):
    headers = _build_auth_headers(request)
    if not headers:
        return RedirectResponse(url="/directlogin", status_code=302)

    # Manual validation
    raw = (count or "").strip()
    if not raw.isdigit():
        return RedirectResponse(
            url="/profile?message=" + quote("Inserisci un numero intero") + "&message_type=danger",
            status_code=302
        )

    n = int(raw)
    if n < 1:
        return RedirectResponse(
            url="/profile?message=" + quote("Il numero di birre deve essere almeno 1") + "&message_type=danger",
            status_code=302
        )
    if n > 500:  # allinea al conint(…le=500) del backend
        return RedirectResponse(
            url="/profile?message=" + quote("Puoi inserire al massimo 500 birre per volta") + "&message_type=danger",
            status_code=302
        )

    try:
        resp = post(f"{BASE_URL}/beers/add_count", json={"count": n, "name": name}, headers=headers)
        resp.raise_for_status()
    except HTTPError as e:
        msg = "Errore nell'aggiunta."
        try:
            er = e.response.json()
            # FastAPI 422 shape: {"detail": [ { "msg": "...", ...}, ... ]}
            if isinstance(er, dict) and "detail" in er:
                det = er["detail"]
                if isinstance(det, list) and det and isinstance(det[0], dict) and "msg" in det[0]:
                    msg = det[0]["msg"]
                elif isinstance(det, str):
                    msg = det
            elif isinstance(er, str):
                msg = er
        except Exception:
            # fall back to plain text body if any
            msg = e.response.text or msg
        # ensure string for quote()
        msg = str(msg)
        return RedirectResponse(
            url="/profile?message=" + quote(msg) + "&message_type=danger",
            status_code=302
        )
    except RequestException as e:
        return RedirectResponse(
            url="/profile?message=" + quote(f"Backend non raggiungibile: {e}") + "&message_type=danger",
            status_code=302
        )

    return RedirectResponse(url="/profile?message=Aggiunte&message_type=success", status_code=302)




@app.post("/logout", response_class=HTMLResponse)
async def logout_post(request: Request):
    headers = _build_auth_headers(request)
    try:
        post(f"{BASE_URL}/logout", headers=headers)
    except RequestException:
        pass
    resp = RedirectResponse(url="/directlogin?message=Sessione%20scaduta&message_type=danger", status_code=302)
    resp.delete_cookie("session_token")
    return resp


# ---------- Friends ----------
@app.get("/friends", response_class=HTMLResponse)
async def friends_page(request: Request, message: str = "", message_type: str = ""):
    headers = _build_auth_headers(request)
    if not headers:
        return RedirectResponse(url="/directlogin?message=Sessione%20scaduta&message_type=danger", status_code=302)

    requests_data = await make_backend_request(
        request, "get", "/friends/requests",
        success_template=None,
        error_template="login.html",
    )
    if isinstance(requests_data, RedirectResponse):
        return requests_data

    friends_data = await make_backend_request(
        request, "get", "/friends",
        success_template=None,
        error_template="login.html",
    )
    if isinstance(friends_data, RedirectResponse):
        return friends_data

    return templates.TemplateResponse(
        "friends.html",
        {
            "request": request,
            "requests": requests_data,
            "friends": friends_data.get("items", []),
            "message": message,
            "message_type": message_type,  # <-- passa il tipo all'alert del base.html
        },
    )

@app.post("/beers/{beer_id}/delete", response_class=HTMLResponse)
async def delete_beer_front(request: Request, beer_id: int):
    headers = _build_auth_headers(request)
    if not headers:
        return RedirectResponse(url="/directlogin?message=Sessione%20scaduta&message_type=danger", status_code=302)
    try:
        resp = post(f"{BASE_URL}/beers/{beer_id}/delete", headers=headers)
        resp.raise_for_status()
        return RedirectResponse("/profile?message=" + quote("Voce eliminata") + "&message_type=success", status_code=302)
    except HTTPError as e:
        msg = "Impossibile eliminare."
        if e.response is not None:
            try:
                msg = e.response.json().get("detail", msg)
            except Exception:
                msg = e.response.text or msg
        return RedirectResponse("/profile?message=" + quote(msg) + "&message_type=danger", status_code=302)
    except RequestException as e:
        return RedirectResponse("/profile?message=" + quote(f"Backend non raggiungibile: {e}") + "&message_type=danger", status_code=302)


@app.post("/beers/{beer_id}/decrement", response_class=HTMLResponse)
async def decrement_beer_front(request: Request, beer_id: int):
    headers = _build_auth_headers(request)
    if not headers:
        return RedirectResponse(url="/directlogin?message=Sessione%20scaduta&message_type=danger", status_code=302)
    try:
        resp = post(f"{BASE_URL}/beers/{beer_id}/decrement", headers=headers)
        resp.raise_for_status()
        return RedirectResponse("/profile?message=" + quote("Aggiornato") + "&message_type=success", status_code=302)
    except HTTPError as e:
        msg = "Impossibile aggiornare."
        if e.response is not None:
            try:
                msg = e.response.json().get("detail", msg)
            except Exception:
                msg = e.response.text or msg
        return RedirectResponse("/profile?message=" + quote(msg) + "&message_type=danger", status_code=302)
    except RequestException as e:
        return RedirectResponse("/profile?message=" + quote(f"Backend non raggiungibile: {e}") + "&message_type=danger", status_code=302)

@app.post("/friends/request", response_class=HTMLResponse)
async def friends_request(request: Request, username: str = Form(...)):
    headers = _build_auth_headers(request)
    if not headers:
        return RedirectResponse(url="/directlogin?message=Sessione%20scaduta&message_type=danger", status_code=302)

    try:
        resp = post(f"{BASE_URL}/friends/request", json={"to_username": username}, headers=headers)
        resp.raise_for_status()
        # OK
        return RedirectResponse(
            url="/friends?message=" + quote("Richiesta inviata") + "&message_type=success",
            status_code=302
        )       

    except HTTPError as e:
        msg = "Errore nell'invio della richiesta."
        if e.response is not None:
            try:
                # prova ad estrarre "detail" dal backend
                msg = e.response.json().get("detail", msg)
            except Exception:
                msg = e.response.text or msg
        return RedirectResponse(
            url="/friends?message=" + quote(msg) + "&message_type=danger",
            status_code=302
        )
    except RequestException as e:
        return RedirectResponse(
            url="/friends?message=" + quote(f"Backend non raggiungibile: {e}") + "&message_type=danger",
            status_code=302
        )

@app.post("/friends/respond", response_class=HTMLResponse)
async def friends_respond(request: Request, request_id: int = Form(...), action: str = Form(...)):
    headers = _build_auth_headers(request)
    if not headers:
        return RedirectResponse(url="/directlogin?message=Sessione%20scaduta&message_type=danger", status_code=302)

    try:
        resp = post(
            f"{BASE_URL}/friends/respond",
            json={"request_id": request_id, "action": action},
            headers=headers
        )
        resp.raise_for_status()
        # messaggio di successo
        if action == "accept":
            msg = "Richiesta accettata"
        elif action == "decline":
            msg = "Richiesta rifiutata"
        else:
            msg = "Azione completata"
        return RedirectResponse(
            url="/friends?message=" + quote(msg) + "&message_type=success",
            status_code=302
        )
    except HTTPError as e:
        msg = "Errore nella risposta alla richiesta."
        if e.response is not None:
            try:
                msg = e.response.json().get("detail", msg)
            except Exception:
                msg = e.response.text or msg
        return RedirectResponse(
            url="/friends?message=" + quote(msg) + "&message_type=danger",
            status_code=302
        )
    except RequestException as e:
        return RedirectResponse(
            url="/friends?message=" + quote(f"Backend non raggiungibile: {e}") + "&message_type=danger",
            status_code=302
        )



# ---------- Public user profile ----------
@app.get("/u/{username}", response_class=HTMLResponse)
async def user_profile(request: Request, username: str, message: str = "", message_type: str = "success"):
    headers = _build_auth_headers(request)
    if not headers:
        return RedirectResponse(url="/directlogin?message=Sessione%20scaduta&message_type=danger", status_code=302)

    user_data = await make_backend_request(
        request, "get", f"/users/{quote(username)}",
        success_template=None,
        error_template="login.html",
    )
    if isinstance(user_data, RedirectResponse):
        return user_data

    beers_data = await make_backend_request(
        request, "get", f"/users/{quote(username)}/beers",
        success_template=None,
        error_template="login.html",
    )
    if isinstance(beers_data, RedirectResponse):
        return beers_data

    items = beers_data.get("items", [])
    for b in items:
        url = (b.get("image_url") or "")
        if url.startswith("/media/"):
            b["image_url"] = url.replace("/media/", "/bmedia/", 1)

    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "profile": user_data,
            "beers": items,
            "message": message,
            "message_type": message_type,
            "is_owner": False,
        },
    )


@app.get("/bmedia/{path:path}")
def proxy_media(path: str):
    # Prende i file media dal backend interno (backend-birbs:8001) e li espone su /bmedia
    upstream = f"{BASE_URL}/media/{path}"
    r = get(upstream, stream=True)
    r.raise_for_status()
    # Propaga il Content-Type se noto
    content_type = r.headers.get("Content-Type", "application/octet-stream")
    return StreamingResponse(r.raw, media_type=content_type)
