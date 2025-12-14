from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import json
import requests

from db import (
    init_db,
    cleanup_expired_records,
    authenticate_user,
    create_user,
    user_exists,
    get_user_balance,
    fetch_recent_artworks_for_user,
    list_public_artworks,
    fetch_artwork_by_id,
    create_artwork_record,
    update_artwork,
    delete_artwork,
    purchase_artwork,
    fetch_transactions_for_user,
    save_artwork_settings,
    get_artwork_settings,
    search_artworks,
    check_connect,
)

from security import is_safe_url, load_artwork_settings, save_artwork_description

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# Initialize DB
init_db()


@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    if not user_exists(session['username']):
        return redirect(url_for('login'))

    balance = get_user_balance(session['user_id'])
    artworks = fetch_recent_artworks_for_user(session['user_id'])
    public_artworks = list_public_artworks()

    return render_template(
        'index.html',
        user=session['username'],
        balance=balance,
        artworks=artworks,
        public_artworks=public_artworks,
    )


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not username or not password:
            return render_template('login.html', error="Введите логин и пароль")

        user = authenticate_user(username, password)
        if user:
            session['username'] = user['username']
            session['user_id'] = user['id']
            return redirect(url_for('index'))

        return render_template('login.html', error="Неверный логин или пароль")

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not username or not password:
            return render_template('register.html', error="Введите логин и пароль")

        ok, user_id = create_user(username, password)
        if ok:
            session['username'] = username
            session['user_id'] = user_id
            return redirect(url_for('index'))

        return render_template('register.html', error="Пользователь уже существует")

    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/create_artwork', methods=['GET', 'POST'])
def create_artwork():
    if 'username' not in session:
        return redirect(url_for('login'))
    if not user_exists(session['username']):
        return redirect(url_for('login'))

    balance = get_user_balance(session['user_id'])

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        data = request.form.get('data', '').strip()
        price = request.form.get('price', '0').strip()
        is_private = 1 if request.form.get('is_private') == 'on' else 0
        signature = request.form.get('signature', '').strip()
        description = request.form.get('description', '').strip()

        try:
            price_int = int(price)
        except ValueError:
            return render_template('create_artwork.html', user=session['username'], balance=balance, error="Цена должна быть числом")

        if not title or not data:
            return render_template('create_artwork.html', user=session['username'], balance=balance, error="Заполните все поля")

        # Save description as plain text (safe)
        settings_data = save_artwork_description(description)

        create_artwork_record(
            owner_id=session['user_id'],
            title=title,
            data=data,
            price=price_int,
            is_private=is_private,
            signature=signature,
            settings_data=settings_data,
        )

        return redirect(url_for('index'))

    return render_template('create_artwork.html', user=session['username'], balance=balance)


@app.route('/edit_artwork/<int:artwork_id>', methods=['GET', 'POST'])
def edit_artwork(artwork_id):
    if 'username' not in session:
        return redirect(url_for('login'))
    if not user_exists(session['username']):
        return redirect(url_for('login'))

    artwork = fetch_artwork_by_id(artwork_id)
    if not artwork or artwork['owner_id'] != session['user_id']:
        return redirect(url_for('index'))

    balance = get_user_balance(session['user_id'])

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        data = request.form.get('data', '').strip()
        price = request.form.get('price', '0').strip()
        is_private = 1 if request.form.get('is_private') == 'on' else 0
        signature = request.form.get('signature', '').strip()

        try:
            price_int = int(price)
        except ValueError:
            return render_template('edit_artwork.html', user=session['username'], balance=balance, artwork=artwork, error="Цена должна быть числом")

        if not title or not data:
            return render_template('edit_artwork.html', user=session['username'], balance=balance, artwork=artwork, error="Заполните все поля")

        update_artwork(
            artwork_id=artwork_id,
            title=title,
            data=data,
            price=price_int,
            is_private=is_private,
            signature=signature,
        )

        return redirect(url_for('index'))

    # Load settings/description safely
    settings_raw = get_artwork_settings(artwork_id)
    settings_obj = load_artwork_settings(settings_raw) if settings_raw else None
    description = ""
    if isinstance(settings_obj, dict) and "description" in settings_obj:
        description = settings_obj.get("description", "")

    return render_template('edit_artwork.html', user=session['username'], balance=balance, artwork=artwork, description=description)


@app.route('/delete_artwork/<int:artwork_id>', methods=['POST'])
def delete_artwork_route(artwork_id):
    if 'username' not in session:
        return redirect(url_for('login'))
    if not user_exists(session['username']):
        return redirect(url_for('login'))

    delete_artwork(artwork_id, session['user_id'])
    return redirect(url_for('index'))


@app.route('/buy/<int:artwork_id>', methods=['POST'])
def buy_artwork(artwork_id):
    if 'username' not in session:
        return redirect(url_for('login'))
    if not user_exists(session['username']):
        return redirect(url_for('login'))

    success, msg = purchase_artwork(session['user_id'], artwork_id)
    if not success:
        return render_template('error.html', message=msg)

    return redirect(url_for('index'))


@app.route('/transactions')
def transactions():
    if 'username' not in session:
        return redirect(url_for('login'))
    if not user_exists(session['username']):
        return redirect(url_for('login'))

    balance = get_user_balance(session['user_id'])
    txs = fetch_transactions_for_user(session['user_id'])
    return render_template('transactions.html', user=session['username'], balance=balance, transactions=txs)


@app.route('/settings/<int:artwork_id>', methods=['GET', 'POST'])
def artwork_settings(artwork_id):
    if 'username' not in session:
        return redirect(url_for('login'))
    if not user_exists(session['username']):
        return redirect(url_for('login'))

    artwork = fetch_artwork_by_id(artwork_id)
    if not artwork or artwork['owner_id'] != session['user_id']:
        return redirect(url_for('index'))

    balance = get_user_balance(session['user_id'])
    settings_raw = get_artwork_settings(artwork_id)
    settings_obj = load_artwork_settings(settings_raw) if settings_raw else {}

    if request.method == 'POST':
        # Store settings as JSON (safe)
        colors = request.form.get('colors', '').strip()
        animation = 1 if request.form.get('animation') == 'on' else 0
        public = 1 if request.form.get('public') == 'on' else 0

        settings_to_save = {
            "colors": colors,
            "animation": bool(animation),
            "public": bool(public),
        }
        save_artwork_settings(artwork_id, json.dumps(settings_to_save))
        return redirect(url_for('index'))

    return render_template(
        'settings.html',
        user=session['username'],
        balance=balance,
        artwork=artwork,
        settings=settings_obj,
    )


@app.route('/search')
def search():
    if 'username' not in session:
        return redirect(url_for('login'))
    if not user_exists(session['username']):
        return redirect(url_for('login'))

    query = request.args.get('q', '').strip()
    results = []
    if query:
        results = search_artworks(query)

    balance = get_user_balance(session['user_id'])
    return render_template('search.html', user=session['username'], balance=balance, query=query, results=results)


@app.route('/import_artwork', methods=['GET', 'POST'])
def import_artwork():
    if 'username' not in session:
        return redirect(url_for('login'))
    if not user_exists(session['username']):
        return redirect(url_for('login'))

    preview_content = None
    error = None
    success = None
    fetched_url = None
    balance = get_user_balance(session['user_id'])

    if request.method == 'POST':
        artwork_url = request.form.get('artwork_url', '').strip()

        if artwork_url:
            ok, _ = is_safe_url(artwork_url)
            if not ok:
                error = "Небезопасный URL"
            else:
                try:
                    resp = requests.get(
                        artwork_url,
                        timeout=5,
                        allow_redirects=False,
                        headers={
                            "User-Agent": "ArtAuctionBot/1.0",
                            "Accept": "application/json,text/plain,*/*",
                        },
                    )

                    # Block unsafe redirects (SSRF via 30x)
                    if 300 <= resp.status_code < 400:
                        loc = resp.headers.get("Location", "")
                        if not loc:
                            error = "Некорректный редирект"
                            return render_template(
                                "import_artwork.html",
                                user=session.get("username"),
                                preview_content=None,
                                error=error,
                                success=None,
                                fetched_url=None,
                                balance=balance,
                            )
                        from urllib.parse import urljoin
                        next_url = urljoin(artwork_url, loc)
                        ok2, _ = is_safe_url(next_url)
                        if not ok2:
                            error = "Небезопасный редирект"
                            return render_template(
                                "import_artwork.html",
                                user=session.get("username"),
                                preview_content=None,
                                error=error,
                                success=None,
                                fetched_url=None,
                                balance=balance,
                            )
                        error = "Редиректы запрещены"
                        return render_template(
                            "import_artwork.html",
                            user=session.get("username"),
                            preview_content=None,
                            error=error,
                            success=None,
                            fetched_url=None,
                            balance=balance,
                        )

                    if resp.status_code != 200:
                        error = f"Ошибка загрузки ({resp.status_code})"
                    else:
                        ok_final, _ = is_safe_url(resp.url)
                        if not ok_final:
                            error = "Небезопасный URL ответа"
                            return render_template(
                                "import_artwork.html",
                                user=session.get("username"),
                                preview_content=None,
                                error=error,
                                success=None,
                                fetched_url=None,
                                balance=balance,
                            )

                        preview_content = resp.text[:10000]
                        fetched_url = resp.url

                        try:
                            data = resp.json()
                            if isinstance(data, dict) and 'shapes' in data:
                                title = data.get('title', 'Импортированная композиция')
                                shapes_json = json.dumps(data['shapes'])
                                price = data.get('price', 100)

                                import_id = create_artwork_record(
                                    owner_id=session['user_id'],
                                    title=title,
                                    data=shapes_json,
                                    price=int(price) if str(price).isdigit() else 100,
                                    is_private=0,
                                    signature="imported",
                                )
                                success = f"Импортировано! ID: {import_id}"
                            else:
                                error = "Неверный формат JSON"
                        except Exception:
                            error = "Ответ не является JSON"
                except Exception as e:
                    error = f"Ошибка запроса: {e}"

    return render_template(
        'import_artwork.html',
        user=session.get('username'),
        preview_content=preview_content,
        error=error,
        success=success,
        fetched_url=fetched_url,
        balance=balance,
    )


@app.route('/healthcheck')
def healthcheck():
    return jsonify(check_connect(request.remote_addr))


@app.route('/cleanup')
def cleanup():
    # Optional cleanup endpoint (keep as-is; ideally protect in prod)
    result = cleanup_expired_records()
    return jsonify(result)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
