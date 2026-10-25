"""Local hotel portal: HTTP adapters reuse the existing hotel transactions."""
from datetime import date, timedelta
from functools import wraps
import hmac
import os
from pathlib import Path
import secrets
from werkzeug.exceptions import SecurityError

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
import psycopg2

import auth
import db
import service

BOOKING_FIELDS = ('reservation_id', 'guest_id', 'name', 'phone', 'room_id', 'room_number',
                  'type_name', 'check_in_date', 'check_out_date', 'guest_count', 'rate',
                  'amount', 'status', 'actual_check_in_at', 'actual_check_out_at', 'previous_id')


def positive(value):
    try:
        result = int(value)
    except (ValueError, TypeError):
        raise service.BookingError('Enter a valid positive integer.')
    if not 0 < result <= 2147483647:
        raise service.BookingError('Enter a valid positive integer.')
    return result


def read_date(value):
    try:
        result = date.fromisoformat(value)
        if result.isoformat() != value:
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise service.BookingError('Enter a valid date in YYYY-MM-DD format.')


def booking(reservation_id):
    rows = service.search_reservations(str(reservation_id))
    if not rows:
        abort(404)
    return dict(zip(BOOKING_FIELDS, rows[0]))


def contacts():
    with auth.cursor() as cur:
        cur.execute('SELECT guest_id,name,phone FROM guest ORDER BY guest_id')
        return cur.fetchall()


def staff_required(manager=False, password_page=False):
    def decorate(function):
        @wraps(function)
        def guarded(*args, **kwargs):
            if not g.staff:
                return redirect(url_for('login'))
            if g.staff['must_change_password'] and not password_page:
                return redirect(url_for('password'))
            if manager and g.staff['role'] != 'manager':
                abort(403)
            return function(*args, **kwargs)
        return guarded
    return decorate


def create_app(test_config=None):
    app = Flask(__name__)
    secret_file = Path(__file__).resolve().parents[1] / '.local/web_session.key'
    secret = os.environ.get('HOTEL_SESSION_SECRET')
    if not secret and secret_file.exists():
        secret = secret_file.read_text(encoding='utf-8').strip()
    app.config.update(SECRET_KEY=secret, SESSION_COOKIE_NAME='hotel_staff',
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=False, PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        SESSION_REFRESH_EACH_REQUEST=False, MAX_CONTENT_LENGTH=65536,
        TRUSTED_HOSTS=['127.0.0.1', 'localhost'])
    if test_config:
        app.config.update(test_config)
    if not app.secret_key or len(app.secret_key) < 32:
        raise RuntimeError('Run setup_web.py first to generate a local session signing key.')

    def csrf_token():
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_urlsafe(32)
        return session['csrf_token']

    @app.context_processor
    def context():
        return {'csrf_token': csrf_token, 'staff': getattr(g, 'staff', None)}

    @app.before_request
    def identity_and_csrf():
        g.staff = None
        if session.get('staff_id'):
            try:
                g.staff = auth.require_staff(session['staff_id'], session.get('version'), allow_password_change=True)
            except auth.AuthError:
                session.clear()
        if request.method == 'POST':
            expected = session.get('csrf_token')
            supplied = request.form.get('csrf_token', '')
            if not expected or not hmac.compare_digest(expected.encode('utf-8'), supplied.encode('utf-8')):
                abort(400, description='This page has expired. Reload it before submitting.')
        g.actor_token = service.operation_actor.set(
            ('staff',g.staff['staff_id'],g.staff['session_version']) if g.staff else None)

    @app.teardown_request
    def clear_operation_identity(error=None):
        token = g.pop('actor_token',None)
        if token is not None:
            service.operation_actor.reset(token)

    @app.after_request
    def security_headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self' data:; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        return response

    @app.errorhandler(service.BookingError)
    def business_error(error):
        return render_template('error.html', message=str(error), code=400), 400

    @app.errorhandler(service.StaleReservation)
    def stale_reservation(error):
        return render_template('error.html',message=str(error),code=409),409

    @app.errorhandler(psycopg2.Error)
    def database_error(error):
        app.logger.error('Database operation failed; SQLSTATE=%s', error.pgcode)
        return render_template('error.html', code=503,
            message='The database operation did not complete. If the outcome is uncertain, check the reservation before retrying.'), 503

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    def request_error(error):
        messages = {400: 'Invalid request or expired page. Please reload the page.',
                    403: 'Manager access is required for this action.', 404: 'The page or reservation could not be found.'}
        return render_template('error.html', message=messages[error.code], code=error.code), error.code

    @app.errorhandler(SecurityError)
    def untrusted_host(error):
        # An untrusted Host has no URL adapter, so do not render templates using url_for.
        return 'Invalid request host.', 400

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            try:
                staff = auth.authenticate(request.form.get('username', ''), request.form.get('password', ''))
            except auth.AuthError as error:
                flash(str(error), 'error')
                return render_template('login.html'), 401
            session.clear()
            session.update(staff_id=staff['staff_id'], version=staff['session_version'])
            session.permanent = True
            return redirect(url_for('password' if staff['must_change_password'] else 'dashboard'))
        if g.staff:
            return redirect(url_for('password' if g.staff['must_change_password'] else 'dashboard'))
        return render_template('login.html')

    @app.post('/logout')
    @staff_required(password_page=True)
    def logout():
        auth.logout(g.staff['staff_id'], g.staff['session_version'])
        session.clear()
        return redirect(url_for('login'))

    @app.route('/password', methods=['GET', 'POST'])
    @staff_required(password_page=True)
    def password():
        if request.method == 'POST':
            new = request.form.get('new_password', '')
            if new != request.form.get('confirm_password'):
                raise auth.AuthError('The new passwords do not match.')
            version = auth.change_password(g.staff['staff_id'], g.staff['session_version'],
                                           request.form.get('old_password', ''), new)
            session.clear()
            session.update(staff_id=g.staff['staff_id'], version=version)
            session.permanent = True
            flash('Password updated. Your other sessions have been signed out.', 'success')
            return redirect(url_for('dashboard'))
        return render_template('password.html')

    @app.get('/')
    def availability():
        options = None
        if request.args.get('check_in'):
            options = service.find_rooms(read_date(request.args.get('check_in')),
                read_date(request.args.get('check_out')), positive(request.args.get('guests')),
                positive(request.args['room_type_id']) if request.args.get('room_type_id') else None)
        with auth.cursor() as cur:
            cur.execute('SELECT (CURRENT_TIMESTAMP AT TIME ZONE \'Australia/Sydney\')::date')
            today = cur.fetchone()[0]
        return render_template('availability.html', options=options, types=service.list_types(), today=today)

    @app.route('/book',methods=['GET','POST'])
    def public_booking():
        room_id=positive(request.values.get('room_id'))
        start=read_date(request.values.get('check_in'))
        end=read_date(request.values.get('check_out'))
        guests=positive(request.values.get('guests'))
        room=next((row for row in service.find_rooms(start,end,guests) if row[0]==room_id),None)
        if room is None:
            raise service.BookingError('This room is no longer available. Search again for another room or dates.')
        if request.method=='POST':
            result=service.create_public_reservation(request.form.get('name',''),request.form.get('email',''),
                request.form.get('phone',''),room_id,start,end,guests,request.form.get('quoted_base'))
            token=secrets.token_urlsafe(24)
            # shortcut: retain the latest receipt only; use customer accounts for persistent booking management.
            session['booking_receipt']={'token':token,'reservation_id':result[0]}
            return redirect(url_for('public_booking_receipt',token=token))
        return render_template('public_booking.html',room=room,start=start,end=end,guests=guests)

    @app.get('/booking/confirmation/<token>')
    def public_booking_receipt(token):
        receipt=session.get('booking_receipt')
        if not receipt or not hmac.compare_digest(receipt['token'].encode('utf-8'),token.encode('utf-8')):
            abort(404)
        item=booking(receipt['reservation_id'])
        return render_template('public_receipt.html',item=item)

    @app.get('/dashboard')
    @staff_required()
    def dashboard():
        rows = [dict(zip(BOOKING_FIELDS, row)) for row in service.search_reservations()]
        rooms = service.list_rooms()
        metrics = [len(rooms), sum(r['status'] == 'checked_in' for r in rows),
                   sum(r['status'] == 'confirmed' for r in rows), sum(r[6] != 'clean' for r in rooms)]
        return render_template('dashboard.html', metrics=metrics,
            current=[r for r in rows if r['status'] == 'checked_in'], statistics=service.booking_statistics())

    @app.get('/reservations')
    @staff_required()
    def reservations():
        keyword = request.args.get('keyword', '').strip()
        rows = [dict(zip(BOOKING_FIELDS, row)) for row in service.search_reservations(keyword)]
        status = request.args.get('status', '')
        if status:
            rows = [row for row in rows if row['status'] == status]
        return render_template('reservations.html', rows=rows, keyword=keyword, status=status)

    @app.route('/reservations/new', methods=['GET', 'POST'])
    @staff_required()
    def new_reservation():
        if request.method == 'POST':
            result = service.create_reservation(positive(request.form.get('guest_id')),
                positive(request.form.get('room_id')), read_date(request.form.get('check_in')),
                read_date(request.form.get('check_out')), positive(request.form.get('guests')),
                discount_rate=request.form.get('discount_rate') or None,
                reason=request.form.get('reason',''),quoted_base=request.form.get('quoted_base') or None)
            flash('Reservation created. ID: '+str(result[0]), 'success')
            return redirect(url_for('reservation', reservation_id=result[0]))
        return render_template('new_reservation.html', contacts=contacts(), rooms=service.list_rooms())

    @app.route('/contacts/new', methods=['GET', 'POST'])
    @staff_required()
    def new_contact():
        if request.method == 'POST':
            guest_id = service.add_guest(request.form.get('name', ''), request.form.get('email', ''), request.form.get('phone', ''))
            flash('Contact registered. ID: '+str(guest_id), 'success')
            return redirect(url_for('new_reservation', guest_id=guest_id))
        return render_template('new_contact.html')

    @app.get('/reservations/<int:reservation_id>')
    @staff_required()
    def reservation(reservation_id):
        return render_template('reservation.html', item=booking(reservation_id), roster=service.list_staying_guests(reservation_id),
            history=service.reservation_history(reservation_id))

    @app.route('/reservations/<int:reservation_id>/modify',methods=['GET','POST'])
    @staff_required()
    def modify_reservation(reservation_id):
        item = booking(reservation_id)
        start = request.values.get('check_in') or item['check_in_date'].isoformat()
        end = request.values.get('check_out') or item['check_out_date'].isoformat()
        arrival,departure = read_date(start),read_date(end)
        if request.method == 'POST':
            service.amend_reservation(reservation_id,positive(request.form.get('room_id')),arrival,departure,
                request.form.get('revision'),request.form.get('quoted_base'),request.form.get('reason',''),
                request.form.get('discount_rate') or None)
            flash('Reservation updated. Its previous room and dates are released if no other reservation occupies them.','success')
            return redirect(url_for('reservation',reservation_id=reservation_id))
        type_id = positive(request.args['room_type_id']) if request.args.get('room_type_id') else None
        options, revision = service.amendment_options(reservation_id,arrival,departure,type_id)
        return render_template('modify.html',item=item,options=options,revision=revision,start=start,end=end,
            types=service.list_types())

    @app.route('/reservations/multiple',methods=['GET','POST'])
    @staff_required()
    def multiple_reservations():
        start,end = request.values.get('check_in',''),request.values.get('check_out','')
        options,review,total = None,None,None
        if start:
            arrival,departure = read_date(start),read_date(end)
            options = service.find_rooms(arrival,departure,1)
        if request.method == 'POST':
            if not start:
                raise service.BookingError('Choose stay dates first.')
            contact = positive(request.form.get('guest_id'))
            selected = request.form.getlist('room_id')
            if not selected or len(set(selected)) != len(selected):
                raise service.BookingError('Select distinct rooms for this submission.')
            selections = [{'room_id':positive(rid),'guests':positive(request.form.get('guests_'+rid)),
                'quoted_base':request.form.get('quoted_base_'+rid),
                'discount_rate':request.form.get('discount_rate_'+rid) or None,
                'reason':request.form.get('reason','')} for rid in selected]
            if request.form.get('stage') == 'confirm':
                results = service.create_reservations(contact,arrival,departure,selections)
                return render_template('multiple_success.html',results=results)
            lookup = {row[0]:row for row in options}
            review,total = [],0
            for selection in selections:
                room = lookup.get(selection['room_id'])
                if room is None or selection['guests'] > room[3]:
                    raise service.BookingError('A selected room is unavailable or too small. Search again.')
                base = service._money(selection['quoted_base'])
                if base != room[4]:
                    raise service.BookingError('A price changed. Search again.')
                discount = selection['discount_rate']
                rate = base if discount is None else service._money(discount)
                if discount is not None and (g.staff['role'] != 'manager' or rate>base or not selection['reason'].strip()):
                    raise service.BookingError('Only a manager can confirm a discount, with a reason and a rate no higher than the standard rate.')
                amount = (departure-arrival).days*rate
                review.append(dict(selection,number=room[1],type_name=room[2],rate=rate,amount=amount))
                total += amount
        return render_template('multiple.html',contacts=contacts(),options=options,start=start,end=end,
            review=review,total=total)

    @app.post('/reservations/<int:reservation_id>/action')
    @staff_required()
    def reservation_action(reservation_id):
        item = booking(reservation_id)
        action = request.form.get('action')
        if action == 'check_in':
            service.check_in(reservation_id)
        elif action == 'check_out':
            service.check_out(reservation_id)
        elif action == 'activate':
            service.activate_continuation(reservation_id)
        elif action == 'cancel':
            service.cancel_reservation(item['guest_id'], reservation_id)
        elif action == 'add_guest':
            service.add_staying_guest(reservation_id, request.form.get('full_name', ''))
        elif action == 'remove_guest':
            service.remove_staying_guest(reservation_id, positive(request.form.get('registration_id')))
        else:
            abort(400)
        flash('Action completed.', 'success')
        return redirect(url_for('reservation', reservation_id=reservation_id))

    @app.route('/reservations/<int:reservation_id>/extend', methods=['GET', 'POST'])
    @staff_required()
    def extend(reservation_id):
        item = booking(reservation_id)
        if request.method == 'POST':
            result = service.create_extension(reservation_id, positive(request.form.get('room_id')),
                read_date(request.form.get('new_check_out')), request.form.get('accepted_rate'),
                request.form.get('discount_rate') or None, request.form.get('reason',''))
            flash('Continuation created. The current stay remains active until the next segment is activated.', 'success')
            return redirect(url_for('reservation', reservation_id=result[0]))
        end = request.args.get('new_check_out')
        options = service.find_extension_options(reservation_id, read_date(end)) if end else None
        return render_template('extend.html', item=item, options=options, end=end)

    @app.get('/rooms')
    @staff_required()
    def rooms():
        return render_template('rooms.html', rooms=service.list_rooms())

    @app.post('/rooms/<int:room_id>/housekeeping')
    @staff_required()
    def housekeeping(room_id):
        service.set_housekeeping_status(room_id, request.form.get('status', ''))
        flash('Housekeeping status updated.', 'success')
        return redirect(url_for('rooms'))

    @app.post('/rooms/<int:room_id>/open')
    @staff_required(manager=True)
    def room_open(room_id):
        if request.form.get('is_open') not in ('true', 'false'):
            abort(400)
        service.set_room_open(room_id, request.form['is_open'] == 'true')
        flash('Room booking status updated.', 'success')
        return redirect(url_for('rooms'))

    @app.route('/staff', methods=['GET', 'POST'])
    @staff_required(manager=True)
    def staff_admin():
        if request.method == 'POST':
            action = request.form.get('action')
            args = (g.staff['staff_id'], g.staff['session_version'])
            if action in ('create', 'reset') and request.form.get('password') != request.form.get('confirm_password'):
                raise auth.AuthError('The temporary passwords do not match.')
            if action == 'create':
                auth.create_staff(*args, request.form.get('username', ''), request.form.get('display_name', ''),
                                  request.form.get('password', ''), request.form.get('role', ''))
            elif action == 'active':
                if request.form.get('active') not in ('true', 'false'):
                    abort(400)
                auth.set_active(*args, positive(request.form.get('staff_id')), request.form['active'] == 'true')
            elif action == 'reset':
                auth.reset_password(*args, positive(request.form.get('staff_id')), request.form.get('password', ''))
            else:
                abort(400)
            flash('Staff account updated.', 'success')
            return redirect(url_for('staff_admin'))
        return render_template('staff.html', people=auth.list_staff(g.staff['staff_id'], g.staff['session_version']))

    return app
